"""System and sync status helpers."""

from __future__ import annotations

from app.db.database import Database
from app.services.projects import ProjectService


class SystemService:
    def __init__(self, db: Database, projects: ProjectService):
        self.db = db
        self.projects = projects

    def status(self) -> dict:
        with self.db.connect() as conn:
            sync_rows = conn.execute(
                "SELECT source, last_success_at, last_error_at, last_error_summary FROM sync_state ORDER BY source"
            ).fetchall()
            project_count = conn.execute("SELECT COUNT(*) AS count FROM projects").fetchone()["count"]
            candidate_count = conn.execute("SELECT COUNT(*) AS count FROM discovery_candidates").fetchone()["count"]
            run_count = conn.execute("SELECT COUNT(*) AS count FROM agent_runs").fetchone()["count"]
        attention_queue = self.projects.list_attention_queue()
        attention_summary = {"high": 0, "medium": 0, "low": 0}
        for issue in attention_queue:
            severity = str(issue["severity"])
            if severity in attention_summary:
                attention_summary[severity] += 1
        return {
            "projects": project_count,
            "candidates": candidate_count,
            "runs": run_count,
            "attention": attention_summary,
            "attention_count": len(attention_queue),
            "sync_state": [dict(row) for row in sync_rows],
        }
