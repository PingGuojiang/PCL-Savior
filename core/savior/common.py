from __future__ import annotations
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, asdict, replace
from pathlib import Path
from .models import PatchError, PatchStatus, PatchEdit


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


@dataclass(frozen=True)
class BackupState:
    target: str
    backup: str
    original_sha256: str
    patched_sha256: str
    file_version: str
    patch_id: str
    phase: str = "prepared"


def state_path(target, patch_id):
    target = Path(target).resolve()
    if not patch_id or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for c in patch_id
    ):
        raise PatchError("无效规则编号")
    key = hashlib.sha256(str(target).casefold().encode()).hexdigest()[:16]
    return target.parent / ".pcl-savior" / f"{key}-{patch_id}.json"


def load_backup_state(target, patch_id):
    target = Path(target).resolve()
    record = state_path(target, patch_id)
    if not record.exists():
        return None
    try:
        state = BackupState(**json.loads(record.read_text("utf-8")))
        if Path(state.target).resolve() != target or state.patch_id != patch_id:
            raise ValueError("target mismatch")
        backup = Path(state.backup).resolve()
        if backup.parent != record.parent.resolve() or backup.suffix != ".bak":
            raise ValueError("backup path mismatch")
        return state
    except (OSError, ValueError, TypeError) as e:
        raise PatchError("备份记录无效，已停止操作") from e


def _write_backup_state(target, state):
    record = state_path(target, state.patch_id)
    record.parent.mkdir(exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".journal-", dir=record.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(asdict(state), f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, record)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def assert_target_not_running(target):
    import psutil

    target = Path(target).resolve()
    wanted = os.path.normcase(str(target))
    try:
        for proc in psutil.process_iter():
            if proc.pid in (0, 4, os.getpid()):
                continue
            try:
                name = proc.name().casefold()
                if name not in (
                    target.name.casefold(),
                    "java.exe",
                    "javaw.exe",
                    "java",
                    "javaw",
                ):
                    continue
                exe = proc.exe()
                if exe and os.path.normcase(str(Path(exe).resolve())) == wanted:
                    raise PatchError("启动器正在运行，请关闭后再操作")
                if Path(exe or "").stem.lower() in ("java", "javaw"):
                    args = proc.cmdline()
                    cwd = None
                    for i, arg in enumerate(args[:-1]):
                        if arg.lower() == "-jar":
                            candidate = Path(args[i + 1])
                            cwd = proc.cwd() if not candidate.is_absolute() else None
                            candidate = (
                                Path(cwd) / candidate if cwd else candidate
                            ).resolve()
                            if os.path.normcase(str(candidate)) == wanted:
                                raise PatchError("HMCL 正在运行，请关闭后再操作")
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except psutil.AccessDenied as e:
                raise PatchError("无法检查进程占用；请以有权限的账户重试") from e
    except psutil.Error as e:
        raise PatchError("进程检查失败；已停止操作") from e


def assert_processes_not_running(process_names):
    raise PatchError("必须按目标文件路径检查进程")


@contextmanager
def _target_lock(target):
    # OS byte-range lock serializes our operations; a Windows read handle denies writes.
    lock = (
        target.parent
        / ".pcl-savior"
        / (hashlib.sha256(str(target).encode()).hexdigest()[:16] + ".lock")
    )
    lock.parent.mkdir(exist_ok=True)
    stream = lock.open("a+b")
    try:
        if stream.seek(0, 2) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        stream.close()
        raise PatchError("另一个操作正在处理该文件") from e
    handle = None
    kernel = None
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            create = kernel.CreateFileW
            create.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ]
            create.restype = wintypes.HANDLE
            # Deny writes while preparing. Close immediately before Windows atomic replacement.
            handle = create(str(target), 0x80000000, 0x1 | 0x4, None, 3, 0x80, None)
            if handle == wintypes.HANDLE(-1).value:
                handle = None
                raise PatchError("无法锁定启动器文件；请关闭占用它的程序")

        def release_target():
            nonlocal handle
            if handle is not None:
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel.CloseHandle(handle)
                handle = None

        yield release_target
    finally:
        if handle is not None:
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(handle)
        try:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
        finally:
            stream.close()


def _apply_edits(data, edits):
    result = bytearray(data)
    previous = 0
    for e in sorted(edits, key=lambda e: e.offset):
        end = e.offset + len(e.original)
        if (
            e.offset < previous
            or e.offset < 0
            or not e.original
            or end > len(data)
            or len(e.original) != len(e.replacement)
        ):
            raise PatchError("补丁区间无效")
        if data[e.offset : end] != e.original:
            raise PatchError("文件内容已变化，已停止操作")
        result[e.offset : end] = e.replacement
        previous = end
    return bytes(result)


def _write_temp(target, data):
    fd, temp = tempfile.mkstemp(
        prefix="." + target.stem + "-", suffix=target.suffix, dir=target.parent
    )
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    return Path(temp)


def install_patched_payload(
    target,
    patched,
    file_version,
    patch_id,
    inspector,
    expected_sha256=None,
    recovery_original=None,
):
    target = Path(target).resolve()
    with _target_lock(target) as release_target:
        assert_target_not_running(target)
        original = target.read_bytes()
        digest = sha256_bytes(original)
        if expected_sha256 is None or digest != expected_sha256.upper():
            raise PatchError("文件已在检测后变化；请重新检测")
        state = load_backup_state(target, patch_id)
        if state:
            backup = Path(state.backup)
            if not backup.is_file() or sha256_file(backup) != state.original_sha256:
                raise PatchError("原始备份缺失或被修改")
            if digest not in (state.original_sha256, state.patched_sha256):
                raise PatchError("文件与备份记录不匹配")
            if digest == sha256_bytes(patched) == state.patched_sha256:
                return replace(
                    inspector(target), backup_available=True, rule_id=patch_id
                )
        temp = _write_temp(target, patched)
        try:
            if inspector(temp).status != PatchStatus.PATCHED:
                raise PatchError("修补结果结构校验失败")
            if sha256_file(temp) != sha256_bytes(patched):
                raise PatchError("临时文件校验失败")
            if state is None:
                backup_data = (
                    recovery_original if recovery_original is not None else original
                )
                original_digest = sha256_bytes(backup_data)
                record = state_path(target, patch_id)
                backup = record.with_name(record.stem + "-" + original_digest + ".bak")
                if backup.exists():
                    if sha256_file(backup) != original_digest:
                        raise PatchError("现有备份已变化，拒绝覆盖")
                else:
                    with backup.open("xb") as f:
                        f.write(backup_data)
                        f.flush()
                        os.fsync(f.fileno())
                if sha256_file(backup) != original_digest:
                    raise PatchError("备份校验失败")
                state = BackupState(
                    str(target),
                    str(backup),
                    original_digest,
                    sha256_bytes(patched),
                    file_version,
                    patch_id,
                )
            else:
                state = replace(
                    state, patched_sha256=sha256_bytes(patched), phase="prepared"
                )
            _write_backup_state(target, state)
            assert_target_not_running(target)
            if sha256_file(target) != digest:
                raise PatchError("文件已变化；已取消替换")
            release_target()
            os.replace(temp, target)
            _write_backup_state(target, replace(state, phase="installed"))
            return replace(inspector(target), backup_available=True, rule_id=patch_id)
        finally:
            temp.unlink(missing_ok=True)


def restore_patched_payload(target, patch_id, inspector):
    target = Path(target).resolve()
    with _target_lock(target) as release_target:
        assert_target_not_running(target)
        state = load_backup_state(target, patch_id)
        if state is None:
            raise PatchError("没有找到可用备份")
        if sha256_file(state.backup) != state.original_sha256:
            raise PatchError("备份已被修改，拒绝恢复")
        current = sha256_file(target)
        if current not in (state.original_sha256, state.patched_sha256):
            raise PatchError("当前文件已变化，拒绝覆盖")
        if current == state.original_sha256:
            return replace(inspector(target), backup_available=True, rule_id=patch_id)
        temp = _write_temp(target, Path(state.backup).read_bytes())
        try:
            if sha256_file(temp) != state.original_sha256:
                raise PatchError("恢复临时文件校验失败")
            if inspector(temp).status not in (
                PatchStatus.PATCHABLE,
                PatchStatus.NATIVE,
            ):
                raise PatchError("原始备份结构未通过验证")
            _write_backup_state(target, replace(state, phase="restoring"))
            assert_target_not_running(target)
            if sha256_file(target) != current:
                raise PatchError("当前文件已变化，拒绝覆盖")
            release_target()
            os.replace(temp, target)
            _write_backup_state(target, replace(state, phase="restored"))
            return replace(inspector(target), backup_available=True, rule_id=patch_id)
        finally:
            temp.unlink(missing_ok=True)
