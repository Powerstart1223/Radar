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
            active_run_count = conn.execute(
                "SELECT COUNT(*) AS count FROM agent_runs WHERE status IN ('queued', 'running', 'cancelling')"
            ).fetchone()["count"]
        attention_queue = self.projects.list_attention_queue()
        deployments = self.projects.list_deployments()
        attention_summary = {"high": 0, "medium": 0, "low": 0}
        for issue in attention_queue:
            severity = str(issue["severity"])
            if severity in attention_summary:
                attention_summary[severity] += 1
        deploy_summary = {"failed": 0, "active": 0, "available": 0, "manual": 0}
        for deployment in deployments:
            state = str(deployment.get("state") or "")
            if state == "failed":
                deploy_summary["failed"] += 1
            elif state in {"queued", "running", "cancelling"}:
                deploy_summary["active"] += 1
            elif state == "manual":
                deploy_summary["manual"] += 1
            elif state == "available":
                deploy_summary["available"] += 1
        return {
            "projects": project_count,
            "candidates": candidate_count,
            "runs": run_count,
            "active_runs": active_run_count,
            "deployments": len(deployments),
            "deploy_summary": deploy_summary,
            "attention": attention_summary,
            "attention_count": len(attention_queue),
            "sync_state": [dict(row) for row in sync_rows],
        }
