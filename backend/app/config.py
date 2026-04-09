from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _default_runtime_root() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "AuditControlCenter"

    home = Path.home()
    if os.name == "posix" and "darwin" in os.sys.platform:
        return home / "Library" / "Application Support" / "AuditControlCenter"

    return home / ".local" / "share" / "AuditControlCenter"


def _default_database_url() -> str:
    env_runtime_root = os.getenv("AUDIT_RUNTIME_DIR")
    candidate_roots = [Path(env_runtime_root)] if env_runtime_root else []
    candidate_roots.append(_default_runtime_root())
    candidate_roots.append(PROJECT_ROOT / "backend" / "runtime")

    for root in candidate_roots:
        try:
            root.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{(root / 'audit_system.db').as_posix()}"
        except OSError:
            continue

    return "sqlite:///:memory:"


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        _default_database_url(),
    )
    api_title: str = "WhatsApp Audit Control Center"
    runtime_dir: Path = Path(os.getenv("AUDIT_RUNTIME_DIR", str(_default_runtime_root())))
    media_dir: Path = Path(os.getenv("BOT_MEDIA_DIR", str(runtime_dir / "media" / "images")))
    reports_dir: Path = Path(os.getenv("AUDIT_REPORTS_DIR", str(runtime_dir / "reports")))
    bot_auth_dir: Path = Path(os.getenv("BOT_AUTH_DIR", str(runtime_dir / "bot-auth")))
    frontend_dir: Path = PROJECT_ROOT / "frontend"
    ollama_url: str | None = os.getenv("OLLAMA_URL")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "mistral")


settings = Settings()
