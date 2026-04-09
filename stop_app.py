from __future__ import annotations

import os
import signal
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RUN_DIR = ROOT / ".run"


def stop_pid_file(name: str) -> None:
    pid_path = RUN_DIR / f"{name}.pid"
    if not pid_path.exists():
        return

    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except ValueError:
        pid_path.unlink(missing_ok=True)
        return

    try:
        if os.name == "nt":
            os.system(f"taskkill /PID {pid} /T /F >NUL 2>&1")
        else:
            os.kill(pid, signal.SIGTERM)
    finally:
        pid_path.unlink(missing_ok=True)


def main() -> None:
    stop_pid_file("bot")
    stop_pid_file("backend")


if __name__ == "__main__":
    main()
