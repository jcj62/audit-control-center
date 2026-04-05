from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _default_database_url() -> str:
    local_app_data = os.getenv("LOCALAPPDATA")
    candidate_roots = []

    if local_app_data:
        candidate_roots.append(Path(local_app_data) / "AuditControlCenter")

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
    media_dir: Path = PROJECT_ROOT / "backend" / "media" / "images"
    reports_dir: Path = PROJECT_ROOT / "backend" / "reports"
    frontend_dir: Path = PROJECT_ROOT / "frontend"
    ollama_url: str | None = os.getenv("OLLAMA_URL")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "mistral")


settings = Settings()
