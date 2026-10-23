from __future__ import annotations

import hashlib
import re
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import dnfile
import pefile
from dncil.cil.body.reader import read_method_body_from_bytes

from savior.common import (
    PatchError,
    PatchStatus,
    install_patched_payload,
    restore_patched_payload,
)

PATCH_ID = "pcl2-download-gate-v1"
EXPECTED_ASSEMBLY_PREFIX = "Plain Craft Launcher"
SUPPORTED_VERSION = "2.99.0.0"


from savior.models import PatchEdit, PclInspection


def _version_tuple(value: str) -> tuple[int, int, int, int]:
    numbers = [int(part) for part in re.findall(r"\d+", value)[:4]]
    return tuple(numbers + [0] * (4 - len(numbers)))


def _resource_version(path: Path) -> str:
    pe = (
        pefile.PE(data=path, fast_load=True)
        if isinstance(path, bytes)
        else pefile.PE(str(path), fast_load=True)
    )
    try:
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
        )
        for file_info in getattr(pe, "FileInfo", []):
            for entry in file_info:
                if getattr(entry, "Key", b"") != b"StringFileInfo":
                    continue
                for table in getattr(entry, "StringTable", []):
                    values = getattr(table, "entries", {})
                    for key in (b"FileVersion", b"ProductVersion"):
                        if key in values:
                            return (
                                values[key]
                                .decode("utf-8", errors="replace")
                                .strip("\x00 ")
                            )
        return ""
    finally:
        pe.close()


def _find_type(pe: dnfile.dnPE, type_name: str):
    matches = [
        row for row in pe.net.mdtables.TypeDef.rows if str(row.TypeName) == type_name
    ]
    if len(matches) != 1:
        raise PatchError(f"无法唯一定位类型 {type_name}")
    return matches[0]


def _find_method(pe: dnfile.dnPE, type_name: str, method_name: str):
    type_row = _find_type(pe, type_name)
    matches = [
        item.row for item in type_row.MethodList if str(item.row.Name) == method_name
    ]
    if len(matches) != 1:
        raise PatchError(f"无法唯一定位方法 {type_name}.{method_name}")
    return matches[0]


def _find_field_token(pe: dnfile.dnPE, field_name: str) -> int:
    matches = [
        index
        for index, row in enumerate(pe.net.mdtables.Field.rows, start=1)
        if str(row.Name) == field_name
    ]
    if len(matches) != 1:
        raise PatchError(f"无法唯一定位字段 {field_name}")
    return 0x04000000 | matches[0]


def _body_details(pe: dnfile.dnPE, method) -> tuple[int, list]:
    if not method.Rva:
        raise PatchError(f"方法 {method.Name} 没有 IL 方法体")
    section = pe.get_section_by_rva(method.Rva)
    if section is None:
        raise PatchError(f"无法读取方法 {method.Name} 的 RVA")
    rva_offset = method.Rva - section.VirtualAddress
    body = read_method_body_from_bytes(section.get_data()[rva_offset:])
    file_offset = section.PointerToRawData + rva_offset
    return file_offset, body.instructions


def _coded_row(pe: dnfile.dnPE, coded):
    if hasattr(coded, "row") and coded.row is not None:
        return coded.row
    table = pe.net.mdtables.tables.get(coded.table)
    if table is None:
        return None
    return table.rows[coded.row_index - 1]


def _token_name(pe: dnfile.dnPE, token: int) -> str:
    table = token >> 24
    row_index = token & 0xFFFFFF
    tables = pe.net.mdtables
    if table == 6 and 1 <= row_index <= len(tables.MethodDef.rows):
        return str(tables.MethodDef.rows[row_index - 1].Name)
    if table == 10 and 1 <= row_index <= len(tables.MemberRef.rows):
        return str(tables.MemberRef.rows[row_index - 1].Name)
    if table == 43 and 1 <= row_index <= len(tables.MethodSpec.rows):
        spec = tables.MethodSpec.rows[row_index - 1]
        method = _coded_row(pe, spec.Method)
        return str(method.Name) if method is not None else ""
    if table == 4 and 1 <= row_index <= len(tables.Field.rows):
        return str(tables.Field.rows[row_index - 1].Name)
    return ""


def _ldstr_value(pe, token):
    if token >> 24 != 0x70:
        return ""
    item = pe.net.user_strings.get(token & 0xFFFFFF)
    # dnfile owns the compressed length prefix and final UTF-16 flag parsing.
    # Decoding __data__ directly includes the length prefix and corrupts Chinese.
    value = getattr(item, "value", None)
    return value if isinstance(value, str) else ""


def _instruction_end(instruction) -> int:
    return instruction.offset + instruction.size


def _is_finish_handler(pe, token):
    if token >> 24 != 6:
        return False
    rows = pe.net.mdtables.MethodDef.rows
    index = (token & 0xFFFFFF) - 1
    if not 0 <= index < len(rows):
        return False
    owner = _find_type(pe, "PageDownloadInstall")
    method = rows[index]
    if not any(item.row is method for item in owner.MethodList):
        return False
    target = _find_method(pe, "PageDownloadInstall", "LoadMinecraft_OnFinish")
    if method is target:
        return True
    if not str(method.Name).startswith("_Lambda$__R"):
        return False
    _, body = _body_details(pe, method)
    if tuple(i.opcode.name for i in body) != ("ldarg.0", "call", "ret"):
        return False
    expected = next(0x06000000 | n for n, row in enumerate(rows, 1) if row is target)
    return getattr(body[1].operand, "value", None) == expected


def _find_loader_edit(
    pe: dnfile.dnPE,
    raw: bytes,
    loader_method,
    loader_field_token: int,
) -> tuple[PatchEdit | None, bool, bool]:
    body_offset, instructions = _body_details(pe, loader_method)
    string_positions = [
        index
        for index, instruction in enumerate(instructions)
        if instruction.opcode.name == "ldstr"
        and hasattr(instruction.operand, "value")
        and _ldstr_value(pe, instruction.operand.value) == "关闭下载"
    ]
    expected = (
        "ldsfld",
        "brfalse.s",
        "ldsfld",
        "br.s",
        "ldsfld",
        "ldftn",
        "newobj",
        "dup",
        "stsfld",
        "ldnull",
        "ldc.i4.2",
        "newobj",
    )
    matches = []
    for index in string_positions:
        if index + len(expected) >= len(instructions):
            continue
        sequence = instructions[index + 1 : index + 1 + len(expected)]
        if tuple(item.opcode.name for item in sequence) != expected:
            continue
        # All references and control flow must agree with the known constructor pattern.
        if _token_name(pe, getattr(sequence[5].operand, "value", 0)) not in (
            "_Lambda$__0-0",
            "_Lambda$__1-0",
        ):
            # VB compiler-generated closure numbering is variable; require a lambda name.
            if not _token_name(pe, getattr(sequence[5].operand, "value", 0)).startswith(
                "_Lambda$__"
            ):
                continue
        if any(
            _token_name(pe, getattr(sequence[n].operand, "value", 0)) != ".ctor"
            for n in (6, 11)
        ):
            continue
        if getattr(sequence[0].operand, "value", None) != getattr(
            sequence[8].operand, "value", None
        ):
            continue
        if getattr(sequence[2].operand, "value", None) != getattr(
            sequence[8].operand, "value", None
        ):
            continue
        if (
            sequence[1].operand != sequence[4].offset
            or sequence[3].operand != sequence[9].offset
        ):
            continue
        first = instructions[index]
        last = sequence[-1]
        start = first.offset
        end = _instruction_end(last)
        original = raw[body_offset + start : body_offset + end]
        prefix = bytes([126]) + struct.pack("<I", loader_field_token)
        replacement = prefix + b"\x00" * (end - start - len(prefix))
        edit = PatchEdit(
            offset=body_offset + start,
            original=original,
            replacement=replacement,
            description="恢复 Minecraft 客户端版本下载列表",
        )
        matches.append(edit)
    if len(matches) > 1:
        raise PatchError("下载限制构造器不唯一")
    if matches:
        return matches[0], True, False

    # Exact padded replacement plus the following finish-handler delegate.
    # A real loader field elsewhere in the conditional is never proof of a patch.
    if string_positions:
        return None, False, True
    candidates = []
    for index, instruction in enumerate(instructions):
        if (
            instruction.opcode.name != "ldsfld"
            or getattr(instruction.operand, "value", None) != loader_field_token
        ):
            continue
        padding = instructions[index + 1 : index + 44]
        tail = instructions[index + 44 : index + 47]
        if len(padding) != 43 or any(i.opcode.name != "nop" for i in padding):
            continue
        if len(tail) != 3 or tuple(i.opcode.name for i in tail) != (
            "ldarg.0",
            "ldftn",
            "newobj",
        ):
            continue
        if tail[0].offset != instruction.offset + 48:
            continue
        if (
            not _is_finish_handler(pe, getattr(tail[1].operand, "value", 0))
            or _token_name(pe, getattr(tail[2].operand, "value", 0)) != ".ctor"
        ):
            continue
        expected_bytes = b"\x7e" + struct.pack("<I", loader_field_token) + b"\x00" * 43
        if (
            raw[
                body_offset + instruction.offset : body_offset + instruction.offset + 48
            ]
            != expected_bytes
        ):
            continue
        candidates.append(instruction)
    if len(candidates) > 1:
        raise PatchError("下载列表补丁特征不唯一")
    return None, len(candidates) == 1, False


def _find_visibility_edit(pe, raw, modify_method):
    body_offset, instructions = _body_details(pe, modify_method)
    matches = []
    for index, getter in enumerate(instructions):
        if (
            getter.opcode.name not in ("call", "callvirt")
            or _token_name(pe, getattr(getter.operand, "value", 0))
            != "get_CardMinecraft"
        ):
            continue
        for length in (1, 5):
            seq = instructions[index + 1 : index + 1 + length]
            if len(seq) != length or index + 1 + length >= len(instructions):
                continue
            setter = instructions[index + 1 + length]
            if (
                setter.opcode.name not in ("call", "callvirt")
                or _token_name(pe, getattr(setter.operand, "value", 0))
                != "set_Visibility"
            ):
                continue
            value = None
            patched = False
            if length == 1 and seq[0].opcode.name in ("ldc.i4.0", "ldc.i4.2"):
                value = seq[0]
                patched = value.opcode.name == "ldc.i4.0"
            elif length == 5:
                gate, branch, first, jump, second = seq
                if (
                    gate.opcode.name != "call"
                    or _token_name(pe, getattr(gate.operand, "value", 0))
                    != "get_RestrictMcDownload"
                ):
                    continue
                if branch.opcode.name not in (
                    "brtrue.s",
                    "brtrue",
                    "brfalse.s",
                    "brfalse",
                ) or jump.opcode.name not in ("br.s", "br"):
                    continue
                if branch.operand != second.offset or jump.operand != setter.offset:
                    continue
                expected = (
                    ("ldc.i4.0", "ldc.i4.2")
                    if branch.opcode.name.startswith("brtrue")
                    else ("ldc.i4.2", "ldc.i4.0")
                )
                names = (first.opcode.name, second.opcode.name)
                if names == ("ldc.i4.0", "ldc.i4.0"):
                    patched = True
                elif names != expected:
                    continue
                value = first if expected[0] == "ldc.i4.2" else second
            if value is None:
                continue
            edit = (
                None
                if patched
                else PatchEdit(
                    body_offset + value.offset,
                    raw[body_offset + value.offset : body_offset + value.offset + 1],
                    b"\x16",
                    "显示 Minecraft 修改卡片",
                )
            )
            matches.append((edit, patched))
    if len(matches) != 1:
        raise PatchError("CardMinecraft.Visibility 的完整 IL 结构不匹配")
    return matches[0]


def inspect_pcl2(path: str | Path) -> PclInspection:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise PatchError("所选文件不存在")

    try:
        raw = target.read_bytes()
        pe = dnfile.dnPE(data=raw)
    except Exception as exc:
        raise PatchError("无法读取 .NET 程序集，请确认这是 PCL2 可执行文件") from exc

    try:
        if pe.net is None or pe.net.mdtables.Assembly is None:
            raise PatchError("所选文件不是 .NET 程序集")
        assembly_rows = pe.net.mdtables.Assembly.rows
        if len(assembly_rows) != 1:
            raise PatchError("无法读取 PCL 程序集信息")
        assembly_row = assembly_rows[0]
        assembly_name = str(assembly_row.Name)
        assembly_version = (
            f"{assembly_row.MajorVersion}.{assembly_row.MinorVersion}."
            f"{assembly_row.BuildNumber}.{assembly_row.RevisionNumber}"
        )
        if not assembly_name.startswith(EXPECTED_ASSEMBLY_PREFIX):
            raise PatchError(f"程序集名称为 {assembly_name!r}，不是预期的 PCL2")

        file_version = _resource_version(raw) or assembly_version
        version_tuple = _version_tuple(file_version)
        digest = hashlib.sha256(raw).hexdigest().upper()

        if file_version != SUPPORTED_VERSION or assembly_version != SUPPORTED_VERSION:
            return PclInspection(
                path=target,
                file_version=file_version,
                assembly_version=assembly_version,
                assembly_name=assembly_name,
                version_tuple=version_tuple,
                sha256=digest,
                size=len(raw),
                status=PatchStatus.UNSUPPORTED,
                message="仅支持 PCL 2.99.0.0，文件版本和程序集版本必须一致；不会修改其他版本。",
                edits=(),
            )

        try:
            loader_method = _find_method(pe, "PageDownloadInstall", "LoaderInit")
            modify_method = _find_method(
                pe, "PageDownloadModify", "LoadInstanceFinished"
            )
            loader_field_token = _find_field_token(pe, "DlClientListLoader")
            if (
                loader_method.Signature.value != b"\x20\x00\x01"
                or not modify_method.Signature.value.startswith(b"\x20\x01\x01\x15\x12")
            ):
                raise PatchError("PCL 限制方法的调用签名不匹配")
        except PatchError:
            return PclInspection(
                path=target,
                file_version=file_version,
                assembly_version=assembly_version,
                assembly_name=assembly_name,
                version_tuple=version_tuple,
                sha256=digest,
                size=len(raw),
                status=PatchStatus.UNSUPPORTED,
                message="PCL 版本已知，但补丁所需的 IL 结构未找到；不会修改文件。",
                edits=(),
            )

        loader_edit, loader_patched, has_restriction_string = _find_loader_edit(
            pe, raw, loader_method, loader_field_token
        )
        visibility_edit, visibility_patched = _find_visibility_edit(
            pe, raw, modify_method
        )
        edits = tuple(edit for edit in (loader_edit, visibility_edit) if edit)

        if loader_edit and visibility_edit:
            return PclInspection(
                path=target,
                file_version=file_version,
                assembly_version=assembly_version,
                assembly_name=assembly_name,
                version_tuple=version_tuple,
                sha256=digest,
                size=len(raw),
                status=PatchStatus.PATCHABLE,
                message="已识别到 PCL 2.99.0.0 的完整下载限制，可以直接修补。",
                edits=edits,
            )

        if loader_patched and visibility_patched:
            return PclInspection(
                path=target,
                file_version=file_version,
                assembly_version=assembly_version,
                assembly_name=assembly_name,
                version_tuple=version_tuple,
                sha256=digest,
                size=len(raw),
                status=PatchStatus.PATCHED,
                message="下载入口和修改卡片已经处于开启状态。",
                edits=(),
            )

        return PclInspection(
            path=target,
            file_version=file_version,
            assembly_version=assembly_version,
            assembly_name=assembly_name,
            version_tuple=version_tuple,
            sha256=digest,
            size=len(raw),
            status=PatchStatus.UNSUPPORTED,
            message="只找到了部分限制特征，为避免损坏文件，已拒绝修补。",
            edits=(),
        )
    finally:
        close = getattr(pe, "close", None)
        if close:
            close()


from savior.common import _apply_edits


def apply_pcl2_patch(
    path: str | Path, inspection: PclInspection | None = None
) -> PclInspection:
    target = Path(path).expanduser().resolve()
    previous = inspection
    inspection = inspect_pcl2(target)
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
    patched = _apply_edits(target.read_bytes(), inspection.edits)
    return install_patched_payload(
        target,
        patched,
        inspection.file_version,
        PATCH_ID,
        inspect_pcl2,
        expected_sha256=inspection.sha256,
    )


def restore_pcl2_backup(path: str | Path) -> PclInspection:
    target = Path(path).expanduser().resolve()
    from savior.common import assert_target_not_running

    assert_target_not_running(target)
    return restore_patched_payload(target, PATCH_ID, inspect_pcl2)
