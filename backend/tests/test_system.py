from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.config import Settings
from app.db.database import Database
from app.services.projects import ProjectService
from app.services.system import SystemService


class SystemServiceStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.db = Database(self.base_dir / "project_radar.db")
        self.db.init()
        self.settings = Settings(
            app_name="Project Radar",
            app_host="127.0.0.1",
            app_port=8787,
            base_dir=self.base_dir,
            storage_dir=self.base_dir / "storage",
            artifacts_dir=self.base_dir / "storage" / "artifacts",
            logs_dir=self.base_dir / "storage" / "logs",
            db_path=self.base_dir / "project_radar.db",
            codex_sessions_root=self.base_dir / "codex",
            openclaw_sessions_root=self.base_dir / "openclaw",
            github_token="",
            vercel_token="",
            netlify_token="",
            render_token="",
        )
        self.projects = ProjectService(self.db, self.settings)
        self.system = SystemService(self.db, self.projects)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_status_counts_only_meaningful_pending_candidates(self) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO discovery_candidates
                (candidate_type, display_name, source, evidence_json, confidence, review_status, created_at)
                VALUES
                ('git_repo', 'project-radar', 'git_scan', '{"repo_path":"C:\\\\Users\\\\SJK\\\\Documents\\\\project-radar"}', 0.95, 'pending', '2026-04-26T00:00:00Z'),
                ('codex_session', 'system32', 'codex_session', '{"repo_path":"","cwd":"C:\\\\Windows\\\\System32"}', 0.45, 'pending', '2026-04-26T00:00:00Z'),
                ('openclaw_session', 'workspace', 'openclaw_session', '{"repo_path":"C:\\\\Users\\\\SJK\\\\.openclaw\\\\workspace","cwd":"C:\\\\Users\\\\SJK\\\\.openclaw\\\\workspace"}', 0.35, 'pending', '2026-04-26T00:00:00Z')
                """
            )
            conn.commit()

        status = self.system.status()

        self.assertEqual(status["candidates"], 1)


if __name__ == "__main__":
    unittest.main()
