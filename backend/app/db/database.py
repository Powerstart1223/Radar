"""Database access for Project Radar."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.db.schema import SCHEMA_STATEMENTS


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)
            conn.commit()
        self.seed_skill_definitions()
        self.seed_sync_sources()

    def seed_skill_definitions(self) -> None:
        skills = (
            ("plan-eng-review", "gstack", "Architecture and implementation review", 1, 1, 0),
            ("office-hours", "gstack", "Product and design thinking session", 1, 1, 0),
            ("review", "gstack", "Code review or diff review", 1, 1, 0),
            ("qa", "gstack", "QA and bug-finding workflow", 1, 1, 0),
        )
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO skill_definitions
                (name, source, description, supports_codex, supports_openclaw, requires_interaction)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                skills,
            )
            conn.commit()

    def seed_sync_sources(self) -> None:
        sources = (("discovery",), ("repo",), ("codex",), ("openclaw",), ("github",), ("deploy",))
        with self.connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO sync_state (source, last_success_at, last_error_at, last_error_summary) VALUES (?, NULL, NULL, NULL)",
                sources,
            )
            conn.commit()
