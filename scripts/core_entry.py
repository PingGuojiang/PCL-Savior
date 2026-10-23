"""PyInstaller entry point, intentionally console-capable for pipe IPC."""
from savior.__main__ import main

if __name__ == '__main__':
    raise SystemExit(main())
