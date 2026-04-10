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


def detect_lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            ip = probe.getsockname()[0]
    except OSError:
        return None

    if ip.startswith("127."):
        return None
    return ip


def app_open_url() -> str:
    if os.getenv("AUDIT_OPEN_URL"):
        return os.environ["AUDIT_OPEN_URL"]

    lan_ip = detect_lan_ip()
    host = lan_ip or "127.0.0.1"
    return f"http://{host}:{BACKEND_PORT}"


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
    env["API_BASE_URL"] = f"http://127.0.0.1:{BACKEND_PORT}"
    return env


def backend_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", BACKEND_PORT), timeout=1):
            return True
    except OSError:
        return False


def write_pid(name: str, pid: int) -> None:
    (RUN_DIR / f"{name}.pid").write_text(str(pid), encoding="utf-8")


def pid_is_running(pid: int) -> bool:
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                check=False,
            )
            return str(pid) in result.stdout

        os.kill(pid, 0)
        return True
    except OSError:
        return False


def pid_file_running(name: str) -> bool:
    pid_path = RUN_DIR / f"{name}.pid"
    if not pid_path.exists():
        return False

    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except ValueError:
        pid_path.unlink(missing_ok=True)
        return False

    if pid_is_running(pid):
        return True

    pid_path.unlink(missing_ok=True)
    return False


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
    if pid_file_running("bot"):
        return

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
    webbrowser.open(app_open_url())


if __name__ == "__main__":
    main()
