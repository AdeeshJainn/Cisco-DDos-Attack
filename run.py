"""Single-command demo launcher serving the engine and built dashboard."""

import os

import uvicorn


def main() -> int:
    uvicorn.run(
        "argus.api.app:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8100")),
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
