from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RUN_DIR = ROOT / ".run"
RUN_DIR.mkdir(parents=True, exist_ok=True)
BACKEND_BIND_HOST = os.getenv("AUDIT_BIND_HOST", "0.0.0.0")
BACKEND_PORT = int(os.getenv("AUDIT_PORT", "8000"))
LOCAL_OPEN_URL = os.getenv("AUDIT_OPEN_URL", f"http://127.0.0.1:{BACKEND_PORT}")


def runtime_root() -> Path:
    if os.getenv("AUDIT_RUNTIME_DIR"):
        return Path(os.environ["AUDIT_RUNTIME_DIR"])

    if os.name == "nt" and os.getenv("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "AuditControlCenter"

    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "AuditControlCenter"

    return home / ".local" / "share" / "AuditControlCenter"


def build_env() -> dict[str, str]:
    runtime_dir = runtime_root()
    env = os.environ.copy()
    env["AUDIT_RUNTIME_DIR"] = str(runtime_dir)
    env["BOT_AUTH_DIR"] = str(runtime_dir / "bot-auth")
    env["BOT_MEDIA_DIR"] = str(runtime_dir / "media" / "images")
    env["AUDIT_REPORTS_DIR"] = str(runtime_dir / "reports")
    env["BOT_INSTANCE_ID"] = str(uuid.uuid4())
    return env


def backend_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", BACKEND_PORT), timeout=1):
            return True
    except OSError:
        return False


def write_pid(name: str, pid: int) -> None:
    (RUN_DIR / f"{name}.pid").write_text(str(pid), encoding="utf-8")


def start_backend(env: dict[str, str]) -> None:
    if backend_running():
        return

    stdout = (RUN_DIR / "backend.stdout.log").open("ab")
    stderr = (RUN_DIR / "backend.stderr.log").open("ab")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            BACKEND_BIND_HOST,
            "--port",
            str(BACKEND_PORT),
        ],
        cwd=ROOT,
        env=env,
        stdout=stdout,
        stderr=stderr,
    )
    write_pid("backend", process.pid)

    for _ in range(20):
        if backend_running():
            return
        time.sleep(1)

    raise RuntimeError("Backend did not start in time. Check .run/backend.stderr.log")


def start_bot(env: dict[str, str]) -> None:
    stdout = (RUN_DIR / "bot.stdout.log").open("ab")
    stderr = (RUN_DIR / "bot.stderr.log").open("ab")
    process = subprocess.Popen(
        ["node", "index.js"],
        cwd=ROOT / "bot",
        env=env,
        stdout=stdout,
        stderr=stderr,
    )
    write_pid("bot", process.pid)


def main() -> None:
    env = build_env()
    start_backend(env)
    start_bot(env)
    webbrowser.open(LOCAL_OPEN_URL)


if __name__ == "__main__":
    main()
