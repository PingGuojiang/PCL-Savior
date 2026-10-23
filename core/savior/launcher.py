from __future__ import annotations
from pathlib import Path
from dataclasses import replace
import zipfile
from .models import PatchError, PatchStatus, PclInspection
from .common import sha256_bytes, load_backup_state
from . import pcl2, pcl_ce, hmcl

RULES = (
    (pcl2.PATCH_ID, pcl2.inspect_pcl2, pcl2.apply_pcl2_patch),
    (pcl_ce.PATCH_ID, pcl_ce.inspect_pcl_ce, pcl_ce.apply_pcl_ce_patch),
    (hmcl.PATCH_ID, hmcl.inspect_hmcl, hmcl.apply_hmcl_patch),
)


def inspect_launcher(path):
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise PatchError("所选文件不存在")
    raw = target.read_bytes()
    errors = []
    candidates = (RULES[2],) if zipfile.is_zipfile(target) else RULES[:2]
    for rule, inspector, _ in candidates:
        try:
            result = inspector(target)
            state = load_backup_state(target, rule)
            available = bool(
                state
                and Path(state.backup).is_file()
                and __import__("savior.common", fromlist=["sha256_file"]).sha256_file(
                    state.backup
                )
                == state.original_sha256
            )
            return replace(result, rule_id=rule, backup_available=available)
        except Exception as exc:
            errors.append(str(exc))
    return PclInspection(
        target,
        "",
        "",
        "",
        (0, 0, 0, 0),
        sha256_bytes(raw),
        len(raw),
        PatchStatus.UNSUPPORTED,
        "无法识别安全修补规则：" + "；".join(errors),
        launcher_name="未知",
    )


def apply_launcher_patch(path, inspection=None, expected_sha256=None):
    if isinstance(path, PclInspection):
        inspection = path
        path = path.path
    target = Path(path).resolve()
    current = inspect_launcher(target)
    if expected_sha256 and current.sha256 != expected_sha256.upper():
        raise PatchError("文件已变化，请重新检测")
    if inspection and (
        inspection.path.resolve() != target or inspection.sha256 != current.sha256
    ):
        raise PatchError("文件已变化，请重新检测")
    if current.status == PatchStatus.PATCHED:
        return current
    if current.status != PatchStatus.PATCHABLE:
        raise PatchError(current.message)
    for rule, _, apply in RULES:
        if current.rule_id == rule:
            apply(target, current)
            return inspect_launcher(target)
    raise PatchError("没有匹配的补丁规则")


def restore_launcher_backup(path, expected_sha256=None):
    if isinstance(path, PclInspection):
        path = path.path
    target = Path(path).resolve()
    if expected_sha256 and sha256_bytes(target.read_bytes()) != expected_sha256.upper():
        raise PatchError("文件已变化，请重新检测")
    from .common import restore_patched_payload

    matches = [
        (rule, inspect) for rule, inspect, _ in RULES if load_backup_state(target, rule)
    ]
    if len(matches) != 1:
        raise PatchError("没有唯一的可用备份")
    rule, inspect = matches[0]
    restore_patched_payload(target, rule, inspect)
    return inspect_launcher(target)


def has_launcher_backup(inspection):
    return inspection.backup_available


def find_launcher_candidates():
    from os import environ

    roots = [
        Path.home() / "Desktop",
        Path.home() / "Downloads",
        Path(environ.get("USERPROFILE", str(Path.home()))) / "Desktop",
    ]
    found = set()
    for root in roots:
        if root.exists():
            for pattern in (
                "*PCL*.exe",
                "*Plain Craft*.exe",
                "*HMCL*.exe",
                "*HMCL*.jar",
            ):
                found.update(p.resolve() for p in root.glob(pattern) if p.is_file())
    return sorted(found)
