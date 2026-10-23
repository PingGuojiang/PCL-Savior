from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

import dnfile
from dncil.cil.body.reader import read_method_body_from_bytes

from savior.common import (
    PatchError,
    PatchStatus,
    install_patched_payload,
    load_backup_state,
    restore_patched_payload,
)
from savior.pcl2 import (
    PatchEdit,
    PclInspection,
    _resource_version,
    _version_tuple,
)

PATCH_ID = "pcl-ce-region-gate-v1"
EMBEDDED_ASSEMBLY_NAME = "PCL.Core"


@dataclass(frozen=True)
class EmbeddedAssembly:
    outer_offset: int
    size: int
    name: str
    version: str
    data: bytes


def _pe_file_size(data: bytes, start: int) -> int | None:
    if start + 64 > len(data):
        return None
    pe_offset = struct.unpack_from("<I", data, start + 60)[0]
    if pe_offset < 4 or pe_offset > 4096:
        return None
    nt = start + pe_offset
    if nt + 24 > len(data) or data[nt : nt + 4] != b"PE\x00\x00":
        return None
    section_count = struct.unpack_from("<H", data, nt + 6)[0]
    optional_size = struct.unpack_from("<H", data, nt + 20)[0]
    optional = nt + 24
    if section_count < 1 or section_count > 96 or optional + optional_size > len(data):
        return None
    magic = struct.unpack_from("<H", data, optional)[0]
    if magic not in (267, 523):
        return None
    sections = optional + optional_size
    if sections + section_count * 40 > len(data):
        return None
    raw_end = 0
    for index in range(section_count):
        header = sections + index * 40
        raw_size = struct.unpack_from("<I", data, header + 16)[0]
        raw_pointer = struct.unpack_from("<I", data, header + 20)[0]
        raw_end = max(raw_end, raw_pointer + raw_size)
    if raw_end < 512 or raw_end > 67108864 or start + raw_end > len(data):
        return None
    return raw_end


def _find_embedded_assembly(data: bytes, assembly_name: str) -> EmbeddedAssembly:
    marker = assembly_name.encode("ascii") + b"\x00"
    offset = -1
    matches = []
    while True:
        offset = data.find(b"MZ", offset + 1)
        if offset < 0:
            break
        size = _pe_file_size(data, offset)
        if size is None:
            continue
        blob = data[offset : offset + size]
        if marker not in blob:
            continue
        try:
            pe = dnfile.dnPE(data=blob)
        except Exception:
            continue
        try:
            if (
                pe.net is None
                or pe.net.mdtables.Assembly is None
                or len(pe.net.mdtables.Assembly.rows) != 1
            ):
                continue
            row = pe.net.mdtables.Assembly.rows[0]
            name = str(row.Name)
            if name != assembly_name:
                continue
            version = (
                f"{row.MajorVersion}.{row.MinorVersion}."
                f"{row.BuildNumber}.{row.RevisionNumber}"
            )
            matches.append(
                EmbeddedAssembly(
                    outer_offset=offset,
                    size=size,
                    name=name,
                    version=version,
                    data=blob,
                )
            )
        finally:
            close = getattr(pe, "close", None)
            if close:
                close()

    if len(matches) != 1:
        raise PatchError(
            "没有在 EXE 中找到唯一且未压缩的 PCL.Core 程序集，这个 PCL2 CE 版本可能使用了不同的打包方式"
        )
    return matches[0]


def _get_restricted_edit(
    assembly: EmbeddedAssembly,
) -> tuple[PatchEdit | None, bool, bool]:
    pe = dnfile.dnPE(data=assembly.data)
    try:
        type_rows = [
            row
            for row in pe.net.mdtables.TypeDef.rows
            if str(row.TypeName) == "RegionAssessment"
        ]
        if len(type_rows) != 1:
            raise PatchError("PCL.Core 中找不到 RegionAssessment")
        methods = [
            item.row
            for item in type_rows[0].MethodList
            if str(item.row.Name) == "get_IsRestricted"
        ]
        if len(methods) != 1:
            raise PatchError("PCL.Core 中找不到 RegionAssessment.IsRestricted")
        method = methods[0]
        section = pe.get_section_by_rva(method.Rva)
        if section is None:
            raise PatchError("无法读取 RegionAssessment.IsRestricted")
        relative_rva = method.Rva - section.VirtualAddress
        body = read_method_body_from_bytes(section.get_data()[relative_rva:])
        body_offset = section.PointerToRawData + relative_rva
        signature = getattr(method.Signature, "value", b"")
        if (
            signature != b"\x20\x00\x02"
            or body.code_size != 22
            or getattr(body, "exception_handlers", ())
        ):
            raise PatchError("IsRestricted 方法签名或大小不匹配")
        ins = body.instructions
        names = tuple(i.opcode.name for i in ins)
        if (
            len(ins) == 22
            and names[:2] == ("ldc.i4.0", "ret")
            and all(n == "nop" for n in names[2:])
        ):
            return None, False, True
        expected = (
            "ldarg.0",
            "call",
            "stloc.0",
            "ldloc.0",
            "brfalse.s",
            "ldloc.0",
            "ldc.i4.2",
            "bne.un.s",
            "ldc.i4.1",
            "stloc.1",
            "br.s",
            "ldc.i4.0",
            "stloc.1",
            "ldloc.1",
            "ret",
        )
        if (
            len(names) != len(expected)
            or names[:8] != expected[:8]
            or names[9:] != expected[9:]
            or names[8] not in ("ldc.i4.0", "ldc.i4.1")
        ):
            raise PatchError("IsRestricted 的完整 IL 与已验证规则不匹配")
        from savior.pcl2 import _find_method

        getter = _find_method(pe, "RegionAssessment", "get_Classification")
        token = getattr(ins[1].operand, "value", 0)
        if (
            token >> 24 != 6
            or not 1 <= (token & 0xFFFFFF) <= len(pe.net.mdtables.MethodDef.rows)
            or pe.net.mdtables.MethodDef.rows[(token & 0xFFFFFF) - 1] is not getter
        ):
            raise PatchError("IsRestricted 引用的属性方法不匹配")
        if (
            ins[4].operand != ins[8].offset
            or ins[7].operand != ins[11].offset
            or ins[10].operand != ins[13].offset
        ):
            raise PatchError("IsRestricted 分支目标不匹配")
        restricted_value = ins[8]
        if restricted_value.opcode.name == "ldc.i4.0":
            return None, True, False
        original = assembly.data[
            body_offset
            + restricted_value.offset : body_offset
            + restricted_value.offset
            + 1
        ]
        return (
            PatchEdit(
                offset=assembly.outer_offset + body_offset + restricted_value.offset,
                original=original,
                replacement=b"\x16",
                description="解除 PCL2 CE 地区下载限制",
            ),
            False,
            False,
        )
    finally:
        close = getattr(pe, "close", None)
        if close:
            close()


def inspect_pcl_ce(path: str | Path) -> PclInspection:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise PatchError("请选择 PCL2 CE 的 EXE 文件")
    data = target.read_bytes()
    assembly = _find_embedded_assembly(data, EMBEDDED_ASSEMBLY_NAME)
    edit, patched, legacy_broken = _get_restricted_edit(assembly)
    file_version = _resource_version(data)
    if not file_version:
        raise PatchError("无法读取 PCL2 CE 文件版本")
    digest = hashlib.sha256(data).hexdigest().upper()

    if legacy_broken:
        try:
            _verified_recovery_original(target)
            backup_exists = True
        except PatchError:
            backup_exists = False
        return PclInspection(
            path=target,
            file_version=file_version,
            assembly_version=assembly.version,
            assembly_name=assembly.name,
            version_tuple=_version_tuple(file_version),
            sha256=digest,
            size=len(data),
            status=PatchStatus.PATCHABLE if backup_exists else PatchStatus.UNSUPPORTED,
            message=(
                "检测到旧版 PCL2 CE 补丁已经损坏。将从校验通过的备份在内存中重建后一次性应用安全补丁。"
                if backup_exists
                else "检测到旧版损坏补丁，但没有找到原始备份，无法安全修复。"
            ),
            edits=(),
            launcher_name="PCL2 CE",
        )

    if edit is not None:
        status = PatchStatus.PATCHABLE
        message = "已识别到 PCL2 CE 地区下载限制，可以直接修补。"
    elif patched:
        status = PatchStatus.PATCHED
        message = "PCL2 CE 的下载限制已经解除。"
    else:
        status = PatchStatus.UNSUPPORTED
        message = "没有识别到可安全修补的地区限制结构。"

    return PclInspection(
        path=target,
        file_version=file_version,
        assembly_version=assembly.version,
        assembly_name=assembly.name,
        version_tuple=_version_tuple(file_version),
        sha256=digest,
        size=len(data),
        status=status,
        message=message,
        edits=(edit,) if edit else (),
        launcher_name="PCL2 CE",
    )


def _apply_edit(data: bytes, edit: PatchEdit) -> bytes:
    from savior.common import _apply_edits

    return _apply_edits(data, (edit,))


def apply_pcl_ce_patch(
    path: str | Path, inspection: PclInspection | None = None
) -> PclInspection:
    target = Path(path).expanduser().resolve()
    previous = inspection
    inspection = inspect_pcl_ce(target)
    if previous is not None and (
        previous.path.resolve() != target or previous.sha256 != inspection.sha256
    ):
        raise PatchError("文件已变化，请重新检测")
    if inspection.status == PatchStatus.PATCHED:
        return inspection
    if inspection.status != PatchStatus.PATCHABLE:
        raise PatchError(inspection.message)
    from savior.common import assert_target_not_running

    assert_target_not_running(target)
    recovery_original = None
    if not inspection.edits:
        recovery_original = _verified_recovery_original(target)
        assembly = _find_embedded_assembly(recovery_original, EMBEDDED_ASSEMBLY_NAME)
        edit, patched_before, broken = _get_restricted_edit(assembly)
        if edit is None or patched_before or broken:
            raise PatchError("原始备份不符合安全修补规则")
        patched = _apply_edit(recovery_original, edit)
        return install_patched_payload(
            target,
            patched,
            inspection.file_version,
            PATCH_ID,
            inspect_pcl_ce,
            expected_sha256=inspection.sha256,
            recovery_original=recovery_original,
        )
    patched = _apply_edit(target.read_bytes(), inspection.edits[0])
    return install_patched_payload(
        target,
        patched,
        inspection.file_version,
        PATCH_ID,
        inspect_pcl_ce,
        expected_sha256=inspection.sha256,
    )


def restore_pcl_ce_backup(path: str | Path) -> PclInspection:
    target = Path(path).expanduser().resolve()
    from savior.common import assert_target_not_running

    assert_target_not_running(target)
    return restore_patched_payload(target, PATCH_ID, inspect_pcl_ce)


def _verified_recovery_original(target):
    import json, re
    from savior.common import sha256_file

    state = load_backup_state(target, PATCH_ID)
    if state is None:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", target.stem)
        record = target.parent / ".mclpatch" / f"{safe}.{PATCH_ID}.json"
        try:
            state = json.loads(record.read_text("utf-8"))
            if (
                Path(state["target"]).resolve() != target
                or state["patch_id"] != PATCH_ID
            ):
                raise ValueError()
            backup = Path(state["backup"]).resolve()
            if backup.parent != record.parent.resolve():
                raise ValueError()
            if (
                sha256_file(target) != state["patched_sha256"].upper()
                or sha256_file(backup) != state["original_sha256"].upper()
            ):
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise PatchError("缺少有效的旧版原始备份") from e
    else:
        backup = Path(state.backup)
        if (
            sha256_file(target) != state.patched_sha256
            or sha256_file(backup) != state.original_sha256
        ):
            raise PatchError("原始备份或当前文件不匹配")
    data = backup.read_bytes()
    assembly = _find_embedded_assembly(data, EMBEDDED_ASSEMBLY_NAME)
    edit, patched, broken = _get_restricted_edit(assembly)
    if edit is None or patched or broken:
        raise PatchError("备份不是已验证的未修补版本")
    return data
