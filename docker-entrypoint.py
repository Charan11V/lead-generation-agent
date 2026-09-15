"""Container entrypoint: Streamlit by default, or any command passed through."""

from __future__ import annotations

import os
import sys


def _flag(value: str, default: str = "false") -> str:
    raw = (value if value != "" else default).strip().lower()
    return "true" if raw in {"1", "true", "yes", "on"} else "false"


def main() -> None:
    if len(sys.argv) > 1:
        os.execvp(sys.argv[1], sys.argv[1:])

    port = os.environ.get("PORT", "8501")
    watcher = os.environ.get("STREAMLIT_WATCHER", "auto")
    run_on_save = _flag(os.environ.get("STREAMLIT_RUN_ON_SAVE", "false"))
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "app.py",
        "--server.address",
        "0.0.0.0",
        "--server.port",
        port,
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
        "--server.fileWatcherType",
        watcher,
        "--server.runOnSave",
        run_on_save,
        # Behind Caddy / reverse proxy
        "--server.enableCORS",
        "false",
        "--server.enableXsrfProtection",
        "true",
        "--server.enableWebsocketCompression",
        "false",
    ]
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
