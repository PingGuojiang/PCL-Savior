from __future__ import annotations

import hashlib
import io
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

from savior.common import (
    PatchError,
    PatchStatus,
    install_patched_payload,
    restore_patched_payload,
)
from savior.pcl2 import PclInspection, _version_tuple

PATCH_ID = "hmcl-region-gate-v1"
REGION_CLASS = "org/jackhuang/hmcl/util/RegionUtils.class"
INTEGRITY_CLASS = "org/jackhuang/hmcl/upgrade/IntegrityChecker.class"
HMCL_MAIN_CLASS = "org.jackhuang.hmcl.Main"
REGION_METHOD = "isIsChinaMainlandNetwork"
INTEGRITY_METHOD = "isSelfVerified"
BOOLEAN_DESCRIPTOR = "()Z"


@dataclass(frozen=True)
class MethodCode:
    data: bytes
    attribute_length_offset: int
    info_start: int
    info_end: int
    code: bytes
    constant_pool: tuple[object, ...]
    max_stack: int = 0
    max_locals: int = 0
    exception_table: tuple = ()


class _ClassParser:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def u1(self) -> int:
        self._check(1)
        value = self.data[self.offset]
        self.offset += 1
        return value

    def u2(self) -> int:
        self._check(2)
        value = struct.unpack_from(">H", self.data, self.offset)[0]
        self.offset += 2
        return value

    def u4(self) -> int:
        self._check(4)
        value = struct.unpack_from(">I", self.data, self.offset)[0]
        self.offset += 4
        return value

    def _check(self, length):
        if length < 0 or self.offset + length > len(self.data):
            raise PatchError("HMCL 类文件被截断")

    def take(self, length: int) -> bytes:
        self._check(length)
        value = self.data[self.offset : self.offset + length]
        self.offset += length
        return value


def _parse_constant_pool(parser: _ClassParser) -> tuple[object, ...]:
    count = parser.u2()
    entries: list[object] = [None] * count
    index = 1
    while index < count:
        tag = parser.u1()
        if tag == 1:
            length = parser.u2()
            entries[index] = (
                "Utf8",
                parser.take(length).decode("utf-8", errors="replace"),
            )
        elif tag in (3, 4):
            entries[index] = (tag, parser.take(4).hex())
        elif tag in (5, 6):
            if index + 1 >= count:
                raise PatchError("无效双槽常量池项")
            entries[index] = (tag, parser.take(8).hex())
            index += 1
        elif tag in (7, 8, 16, 19, 20):
            entries[index] = (tag, parser.u2())
        elif tag in (9, 10, 11, 12, 17, 18):
            entries[index] = (tag, parser.u2(), parser.u2())
        elif tag == 15:
            parser.take(3)
            entries[index] = (tag,)
        else:
            raise PatchError(f"HMCL 类文件包含未知常量池标签 {tag}")
        index += 1
    return tuple(entries)


def _utf8(constant_pool: tuple[object, ...], index: int) -> str:
    if index <= 0 or index >= len(constant_pool):
        return ""
    entry = constant_pool[index]
    if not isinstance(entry, tuple) or not entry or entry[0] != "Utf8":
        return ""
    return str(entry[1])


def _method_ref_name(constant_pool: tuple[object, ...], index: int) -> str:
    if index <= 0 or index >= len(constant_pool):
        return ""
    entry = constant_pool[index]
    if not isinstance(entry, tuple) or len(entry) != 3:
        return ""
    if entry[0] not in (9, 10, 11):
        return ""
    name_and_type = entry[2]
    if name_and_type <= 0 or name_and_type >= len(constant_pool):
        return ""
    nat = constant_pool[name_and_type]
    if not isinstance(nat, tuple) or len(nat) != 3 or nat[0] != 12:
        return ""
    return _utf8(constant_pool, nat[1])


def _read_methods(
    class_data: bytes, expected_class: str | None = None
) -> dict[str, MethodCode]:
    parser = _ClassParser(class_data)
    if parser.u4() != 0xCAFEBABE:
        raise PatchError("HMCL 类文件格式无效")
    minor, major = parser.u2(), parser.u2()
    if (minor, major) != (0, 61):
        raise PatchError("类文件版本不属于已验证的 HMCL Java 17 构建")
    constant_pool = _parse_constant_pool(parser)
    parser.u2()
    this_class = parser.u2()
    parser.u2()
    if expected_class:
        entry = (
            constant_pool[this_class] if 0 < this_class < len(constant_pool) else None
        )
        if (
            not entry
            or entry[0] != 7
            or _utf8(constant_pool, entry[1]) != expected_class
        ):
            raise PatchError("类文件身份不匹配")
    for _ in range(parser.u2()):
        parser.take(2)
    for _ in range(parser.u2()):
        parser.take(6)
        for _ in range(parser.u2()):
            parser.take(2)
            length = parser.u4()
            parser.take(length)

    methods: dict[str, MethodCode] = {}
    method_count = parser.u2()
    for _ in range(method_count):
        access_flags = parser.u2()
        name = _utf8(constant_pool, parser.u2())
        descriptor = _utf8(constant_pool, parser.u2())
        attributes_count = parser.u2()
        for _ in range(attributes_count):
            attribute_name = _utf8(constant_pool, parser.u2())
            length_offset = parser.offset
            length = parser.u4()
            info_start = parser.offset
            parser._check(length)
            info_end = info_start + length
            if attribute_name == "Code" and descriptor == BOOLEAN_DESCRIPTOR:
                info = class_data[info_start:info_end]
                if len(info) < 8:
                    raise PatchError(f"HMCL 方法 {name} 的 Code 属性无效")
                code_length = struct.unpack_from(">I", info, 4)[0]
                if code_length > len(info) - 8:
                    raise PatchError(f"HMCL 方法 {name} 的字节码长度无效")
                code = info[8 : 8 + code_length]
                nested = _ClassParser(info)
                nested.take(8 + code_length)
                exception_table = []
                for _ in range(nested.u2()):
                    start, end, handler, catch = (
                        nested.u2(),
                        nested.u2(),
                        nested.u2(),
                        nested.u2(),
                    )
                    if start >= end or end > code_length or handler >= code_length:
                        raise PatchError("无效异常表")
                    exception_table.append((start, end, handler, catch))
                for _ in range(nested.u2()):
                    nested.take(2)
                    nested.take(nested.u4())
                if nested.offset != len(info):
                    raise PatchError("Code 属性长度不匹配")
                if access_flags & 0x509 == 9:
                    if name in methods:
                        raise PatchError("重复的静态布尔方法")
                    methods[name] = MethodCode(
                        data=class_data,
                        attribute_length_offset=length_offset,
                        info_start=info_start,
                        info_end=info_end,
                        code=code,
                        constant_pool=constant_pool,
                        max_stack=struct.unpack_from(">H", info, 0)[0],
                        max_locals=struct.unpack_from(">H", info, 2)[0],
                        exception_table=tuple(exception_table),
                    )
            parser.offset = info_end
    for _ in range(parser.u2()):
        parser.take(2)
        parser.take(parser.u4())
    if parser.offset != len(class_data):
        raise PatchError("类文件尾部结构无效")
    return methods


# Canonical whole-method fingerprints are bound to validated upstream releases.
# Constant-pool indices are normalized to their full owner/name/descriptor.
KNOWN_METHOD_FINGERPRINTS = {
    REGION_METHOD: {"8982c2c3e6770716f77c143466c377ab2ea39642df4f690725d808c301e68b6a"},
    INTEGRITY_METHOD: {
        "e0e4ff8a18a2247ec5501b0b5b5dd4894ef396659f3669235a247ac4810b18ae"
    },
}


def _java_fingerprint(method):
    import json

    cp = method.constant_pool

    def resolve(index, seen=()):
        if index <= 0 or index >= len(cp) or index in seen:
            raise PatchError("无效常量池引用")
        entry = cp[index]
        if not entry:
            raise PatchError("无效常量池槽位")
        tag = entry[0]
        if tag == "Utf8":
            return entry
        if tag in (7, 8, 16, 19, 20):
            return (tag, resolve(entry[1], seen + (index,)))
        if tag in (9, 10, 11, 12):
            return (
                tag,
                resolve(entry[1], seen + (index,)),
                resolve(entry[2], seen + (index,)),
            )
        return entry

    # Complete instruction boundaries; never search raw operands for opcode bytes.
    operand_sizes = {
        **{n: 1 for n in (16, 18, 21, 22, 23, 24, 25, 54, 55, 56, 57, 58, 169, 188)},
        **{
            n: 2
            for n in (
                17,
                19,
                20,
                132,
                153,
                154,
                155,
                156,
                157,
                158,
                159,
                160,
                161,
                162,
                163,
                164,
                165,
                166,
                167,
                168,
                178,
                179,
                180,
                181,
                182,
                183,
                184,
                187,
                189,
                192,
                193,
                198,
                199,
            )
        },
        185: 4,
        186: 4,
        197: 3,
        200: 4,
        201: 4,
    }
    cp_ops = {
        18,
        19,
        20,
        178,
        179,
        180,
        181,
        182,
        183,
        184,
        185,
        186,
        187,
        189,
        192,
        193,
        197,
    }
    code = method.code
    output = []
    starts = set()
    branches = []
    pos = 0
    while pos < len(code):
        start = pos
        starts.add(start)
        op = code[pos]
        pos += 1
        if op in (170, 171, 196) or op > 201:
            raise PatchError("未知方法字节码结构")
        size = operand_sizes.get(op, 0)
        if pos + size > len(code):
            raise PatchError("方法字节码被截断")
        operand = code[pos : pos + size]
        pos += size
        if op in cp_ops:
            count = 1 if op == 18 else 2
            index = int.from_bytes(operand[:count], "big")
            value = (resolve(index), operand[count:].hex())
        else:
            value = operand.hex()
        if 153 <= op <= 168 or op in (198, 199, 200, 201):
            branches.append(start + int.from_bytes(operand, "big", signed=True))
        output.append((op, value))
    if any(t not in starts for t in branches):
        raise PatchError("方法分支目标无效")
    exceptions = []
    for start, end, handler, catch in method.exception_table:
        if (
            start not in starts
            or handler not in starts
            or (end != len(code) and end not in starts)
        ):
            raise PatchError("异常表边界不是指令边界")
        catch_type = resolve(catch) if catch else None
        if catch and catch_type[0] != 7:
            raise PatchError("异常类型引用无效")
        exceptions.append((start, end, handler, catch_type))
    shape = (method.max_stack, method.max_locals, output, exceptions)
    return hashlib.sha256(
        json.dumps(shape, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def _known_original(method, name):
    return _java_fingerprint(method) in KNOWN_METHOD_FINGERPRINTS[name]


def _is_patched_boolean(method, value):
    return (
        method.code == bytes([4 if value else 3, 172])
        and method.max_stack == 1
        and method.max_locals == 0
        and not method.exception_table
    )


def _patch_boolean_method(class_data: bytes, method_name: str, value: bool) -> bytes:
    method = _read_methods(class_data).get(method_name)
    if method is None:
        raise PatchError(f"HMCL 中找不到静态布尔方法 {method_name}")
    patched_code = bytes([4 if value else 3, 172])
    if _is_patched_boolean(method, value):
        return class_data
    new_info = (
        struct.pack(">HHI", 1, 0, len(patched_code))
        + patched_code
        + struct.pack(">HH", 0, 0)
    )
    return (
        class_data[: method.attribute_length_offset]
        + struct.pack(">I", len(new_info))
        + new_info
        + class_data[method.info_end :]
    )


def _manifest_info(archive: zipfile.ZipFile) -> tuple[str, str]:
    try:
        manifest = archive.read("META-INF/MANIFEST.MF").decode(
            "utf-8", errors="replace"
        )
    except KeyError as exc:
        raise PatchError("所选文件不是有效 HMCL JAR") from exc
    main_class = ""
    version = ""
    for raw_line in manifest.replace("\r\n", "\n").split("\n"):
        if raw_line.startswith("Main-Class:"):
            main_class = raw_line.split(":", 1)[1].strip()
        elif raw_line.startswith("Implementation-Version:"):
            version = raw_line.split(":", 1)[1].strip()
    if main_class != HMCL_MAIN_CLASS:
        raise PatchError("所选 JAR 不是预期的 HMCL 主程序")
    return main_class, version


def inspect_hmcl(path: str | Path) -> PclInspection:
    target = Path(path).expanduser().resolve()
    if not target.is_file() or not zipfile.is_zipfile(target):
        raise PatchError("请选择 HMCL 的 JAR 或 EXE 文件")
    raw = target.read_bytes()
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise PatchError("HMCL 压缩包结构无效") from exc

    with archive:
        _, version = _manifest_info(archive)
        names = set(archive.namelist())
        if any(
            n.upper().startswith("META-INF/")
            and n.upper().endswith((".SF", ".RSA", ".DSA", ".EC"))
            for n in names
        ):
            raise PatchError("不支持带标准 JAR 数字签名的容器")
        if len(names) != len(archive.infolist()):
            raise PatchError("ZIP 包包含重复成员")
        if archive.testzip() is not None:
            raise PatchError("ZIP 成员校验失败")
        if REGION_CLASS not in names:
            return PclInspection(
                path=target,
                file_version=version or "未知",
                assembly_version="Java class",
                assembly_name="HMCL",
                version_tuple=_version_tuple(version),
                sha256=hashlib.sha256(raw).hexdigest().upper(),
                size=len(raw),
                status=(
                    PatchStatus.NATIVE
                    if hashlib.sha256(raw).hexdigest()
                    in {
                        "632c2d8873f5a11dd2ffd8418564174995c6a248de5206668c6be114e943e372"
                    }
                    else PatchStatus.UNSUPPORTED
                ),
                message=(
                    "已验证的官方版本没有地区下载限制。"
                    if hashlib.sha256(raw).hexdigest()
                    == "632c2d8873f5a11dd2ffd8418564174995c6a248de5206668c6be114e943e372"
                    else "HMCL 缺少已知限制类，无法安全判断该版本。"
                ),
                edits=(),
                launcher_name="HMCL",
            )
        region = _read_methods(archive.read(REGION_CLASS), REGION_CLASS[:-6]).get(
            REGION_METHOD
        )
        if region is None:
            raise PatchError("HMCL 的 RegionUtils 结构不受支持")
        region_patched = _is_patched_boolean(region, False)
        region_original = _known_original(region, REGION_METHOD)
        integrity_patched = False
        integrity_original = False
        if INTEGRITY_CLASS in names:
            integrity = _read_methods(
                archive.read(INTEGRITY_CLASS), INTEGRITY_CLASS[:-6]
            ).get(INTEGRITY_METHOD)
            if integrity is not None:
                integrity_patched = _is_patched_boolean(integrity, True)
                integrity_original = _known_original(integrity, INTEGRITY_METHOD)

    digest = hashlib.sha256(raw).hexdigest().upper()
    common = dict(
        path=target,
        file_version=version or "未知",
        assembly_version="Java class",
        assembly_name="HMCL",
        version_tuple=_version_tuple(version),
        sha256=digest,
        size=len(raw),
        edits=(),
        launcher_name="HMCL",
    )
    if region_original and integrity_original:
        return PclInspection(
            **common,
            status=PatchStatus.PATCHABLE,
            message="已识别到 HMCL 地区下载限制，可以修补 JAR 或内置 JAR 的 EXE。",
        )
    if region_patched and integrity_patched:
        return PclInspection(
            **common,
            status=PatchStatus.PATCHED,
            message="HMCL 下载限制已经解除。",
        )
    return PclInspection(
        **common,
        status=PatchStatus.UNSUPPORTED,
        message="HMCL 的类结构只匹配到一部分限制特征，已拒绝修补。",
    )


def _build_patched_container(raw: bytes) -> bytes:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise PatchError("HMCL 压缩包结构无效") from exc
    with archive:
        infos = archive.infolist()
        if len({i.filename for i in infos}) != len(infos):
            raise PatchError("ZIP 包包含重复成员")
        if not infos:
            raise PatchError("HMCL 压缩包为空")
        prefix_length = min(info.header_offset for info in infos)
        prefix = raw[:prefix_length]
        region = _patch_boolean_method(archive.read(REGION_CLASS), REGION_METHOD, False)
        integrity = _patch_boolean_method(
            archive.read(INTEGRITY_CLASS), INTEGRITY_METHOD, True
        )
        output = io.BytesIO()
        output.write(prefix)
        with zipfile.ZipFile(output, "w") as rebuilt:
            rebuilt.comment = archive.comment
            for info in infos:
                name = info.filename
                if name == REGION_CLASS:
                    payload = region
                elif name == INTEGRITY_CLASS:
                    payload = integrity
                else:
                    payload = archive.read(name)
                original_external_attr = info.external_attr
                rebuilt.writestr(info, payload, compress_type=info.compress_type)
                # zipfile invents Unix permissions for an original zero field.
                # Restore it before the central directory is serialized.
                info.external_attr = original_external_attr
        return output.getvalue()


def apply_hmcl_patch(
    path: str | Path, inspection: PclInspection | None = None
) -> PclInspection:
    target = Path(path).expanduser().resolve()
    previous = inspection
    inspection = inspect_hmcl(target)
    if previous is not None and (
        previous.path.resolve() != target or previous.sha256 != inspection.sha256
    ):
        raise PatchError("文件已变化，请重新检测")
    if inspection.status == PatchStatus.PATCHED:
        return inspection
    if inspection.status != PatchStatus.PATCHABLE:
        raise PatchError(inspection.message)
    if target.suffix.lower() == ".exe":
        from savior.common import assert_target_not_running

        assert_target_not_running(target)
    patched = _build_patched_container(target.read_bytes())
    return install_patched_payload(
        target,
        patched,
        inspection.file_version,
        PATCH_ID,
        inspect_hmcl,
        expected_sha256=inspection.sha256,
    )


def restore_hmcl_backup(path: str | Path) -> PclInspection:
    target = Path(path).expanduser().resolve()
    if target.suffix.lower() == ".exe":
        from savior.common import assert_target_not_running

        assert_target_not_running(target)
    return restore_patched_payload(target, PATCH_ID, inspect_hmcl)
