"""Run the native application from a verified, temporary one-file payload."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile


def main():
    bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    archive = bundle / "payload.zip"
    expected = (bundle / "payload.sha256").read_text(encoding="ascii").strip()
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise RuntimeError("Embedded application integrity check failed")
    with tempfile.TemporaryDirectory(prefix="PCL-Savior-") as directory:
        runtime = Path(directory)
        with zipfile.ZipFile(archive) as package:
            for item in package.infolist():
                target = (runtime / item.filename).resolve()
                if not target.is_relative_to(runtime.resolve()):
                    raise RuntimeError("Invalid embedded application path")
            package.extractall(runtime)
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
        if len(sys.argv) == 3 and sys.argv[1] == "--self-check":
            request = {"protocol": 1, "id": "singlefile-check", "command": "settings"}
            result = subprocess.run(
                [str(runtime / "savior-core/savior-core.exe")],
                input=json.dumps(request) + "\n", text=True, encoding="utf-8",
                capture_output=True, timeout=60, cwd=runtime, env=env,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            events = [json.loads(line) for line in result.stdout.splitlines()]
            if result.returncode or not events or events[-1].get("type") != "result":
                raise RuntimeError("Embedded worker self-check failed")
            if events[-1].get("id") != request["id"] or events[-1].get("protocol") != 1:
                raise RuntimeError("Embedded worker protocol mismatch")
            Path(sys.argv[2]).write_text(json.dumps({"ok": True, "protocol": 1,
                "payload_sha256": expected}, indent=2), encoding="utf-8")
            return 0
        process = subprocess.Popen([str(runtime / "PCL Savior.exe")], cwd=runtime, env=env)
        return process.wait()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(error), "PCL Savior", 0x10)
        raise SystemExit(1)
