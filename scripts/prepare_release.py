"""Package only runtime files and public notices into release artifacts."""
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "dist/PCL-Savior"
PAYLOAD = ROOT / "build/public-release"
if PAYLOAD.exists():
    if PAYLOAD.is_symlink() or PAYLOAD.resolve() != ROOT.resolve() / "build/public-release":
        raise RuntimeError("Unexpected release staging path")
    shutil.rmtree(PAYLOAD)
PAYLOAD.mkdir(parents=True)
for name in ("PCL Savior.exe",):
    shutil.copyfile(SOURCE / name, PAYLOAD / name)
for name in ("README.md", "THIRD_PARTY_NOTICES.md"):
    shutil.copyfile(ROOT / name, PAYLOAD / name)
for name in ("assets", "licenses", "savior-core"):
    shutil.copytree(SOURCE / name, PAYLOAD / name,
                    ignore=shutil.ignore_patterns("*.py", "__pycache__", "*.pyc", "*.res", "assets" if name == "assets" else "__unused__"))
allowed_roots = {"assets", "licenses", "savior-core", "PCL Savior.exe", "README.md", "THIRD_PARTY_NOTICES.md"}
if {p.name for p in PAYLOAD.iterdir()} != allowed_roots:
    raise RuntimeError("Unexpected release payload")
archive = ROOT / "dist/PCL-Savior-1.0.0-beta.1-windows-x64.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as out:
    for p in sorted(PAYLOAD.rglob("*")):
        if p.is_file():
            out.write(p, p.relative_to(PAYLOAD).as_posix())
print("Public payload:", PAYLOAD)
print("Portable archive:", archive)
