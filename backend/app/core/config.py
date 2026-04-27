"""Runtime configuration for the local Project Radar service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_host: str
    app_port: int
    base_dir: Path
    storage_dir: Path
    artifacts_dir: Path
    logs_dir: Path
    db_path: Path
    codex_sessions_root: Path
    openclaw_sessions_root: Path
    github_token: str
    vercel_token: str
    netlify_token: str
    render_token: str


def get_settings() -> Settings:
    base_dir = Path(__file__).resolve().parents[3]
    storage_override = os.getenv("PROJECT_RADAR_STORAGE_DIR", "").strip()
    storage_dir = Path(storage_override).expanduser() if storage_override else base_dir / "storage"
    codex_sessions_override = os.getenv("PROJECT_RADAR_CODEX_SESSIONS_ROOT", "").strip()
    openclaw_sessions_override = os.getenv("PROJECT_RADAR_OPENCLAW_SESSIONS_ROOT", "").strip()
    return Settings(
        app_name="Project Radar",
        app_host=os.getenv("PROJECT_RADAR_HOST", "127.0.0.1"),
        app_port=int(os.getenv("PROJECT_RADAR_PORT", "8787")),
        base_dir=base_dir,
        storage_dir=storage_dir,
        artifacts_dir=storage_dir / "artifacts",
        logs_dir=storage_dir / "logs",
        db_path=storage_dir / "project_radar.db",
        codex_sessions_root=Path(codex_sessions_override).expanduser()
        if codex_sessions_override
        else Path.home() / ".codex" / "sessions",
        openclaw_sessions_root=Path(openclaw_sessions_override).expanduser()
        if openclaw_sessions_override
        else Path.home() / ".openclaw" / "agents" / "main" / "sessions",
        github_token=os.getenv("PROJECT_RADAR_GITHUB_TOKEN", "").strip(),
        vercel_token=os.getenv("PROJECT_RADAR_VERCEL_TOKEN", "").strip(),
        netlify_token=os.getenv("PROJECT_RADAR_NETLIFY_TOKEN", "").strip(),
        render_token=os.getenv("PROJECT_RADAR_RENDER_TOKEN", "").strip(),
    )
