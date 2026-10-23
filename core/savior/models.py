from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class PatchError(RuntimeError):
    pass


class PatchStatus(str, Enum):
    PATCHABLE = "patchable"
    PATCHED = "patched"
    NATIVE = "native"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class PatchEdit:
    offset: int
    original: bytes
    replacement: bytes
    description: str


@dataclass(frozen=True)
class PclInspection:
    path: Path
    file_version: str
    assembly_version: str
    assembly_name: str
    version_tuple: tuple[int, int, int, int]
    sha256: str
    size: int
    status: PatchStatus
    message: str
    edits: tuple[PatchEdit, ...] = ()
    launcher_name: str = "PCL2"
    rule_id: str = ""
    backup_available: bool = False


LauncherInspection = PclInspection
Inspection = PclInspection
