"""Preserve upstream notices in the portable distribution."""
from pathlib import Path
import importlib.metadata
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'dist/PCL-Savior/licenses'
OUT.mkdir(parents=True, exist_ok=True)
sdk = ROOT / 'third_party/EUI-NEO'
for path in sdk.rglob('*'):
    if not path.is_file() or '.git' in path.parts:
        continue
    if any(part.upper().startswith(('LICENSE', 'COPYING', 'OFL', 'NOTICE', 'FTL.TXT', 'GPLV2.TXT')) for part in [path.name]):
        destination = OUT / 'EUI-NEO' / path.relative_to(sdk)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
for name in ('pefile', 'dnfile', 'dncil', 'psutil', 'pyinstaller', 'pyinstaller-hooks-contrib'):
    package = importlib.metadata.distribution(name)
    for path in package.files or []:
        if any(part.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')) for part in path.parts):
            source = Path(package.locate_file(path))
            if source.is_file():
                destination = OUT / name / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if python_license.exists():
    shutil.copyfile(python_license, OUT / 'Python-LICENSE.txt')
print('License files:', len(list(OUT.rglob('*'))))
