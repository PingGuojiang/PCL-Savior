import sys

from .protocol import serve


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='strict')
    return serve()


if __name__ == '__main__':
    raise SystemExit(main())
