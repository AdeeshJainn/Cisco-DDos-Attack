"""Single-command demo launcher: boots the engine and serves the built
dashboard from one process."""

import sys


def main() -> int:
    sys.stderr.write(
        "run.py: the demo launcher lands with the replay api and dashboard "
        "phases — until then use `make dev`.\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
