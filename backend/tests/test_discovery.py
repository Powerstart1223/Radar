from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import Settings
from app.db.database import Database
from app.services.discovery import DiscoveryService


class DiscoveryServiceSessionTests(unittest.TestCase):
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
        self.service = DiscoveryService(self.db, self.settings)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_discover_codex_sessions_skips_non_repo_system_paths(self) -> None:
        self.settings.codex_sessions_root.mkdir(parents=True)
        session_file = self.settings.codex_sessions_root / "system.jsonl"
        session_file.write_text(
            '{"type":"session_meta","payload":{"cwd":"C:\\\\Windows\\\\System32","id":"session-1"}}\n',
            encoding="utf-8",
        )

        with patch.object(self.service, "_find_git_root", return_value=None):
            candidates = self.service._discover_codex_sessions()

        self.assertEqual(candidates, [])

    def test_discover_codex_sessions_keeps_repo_backed_paths(self) -> None:
        repo = self.base_dir / "project-radar"
        repo.mkdir()
        (repo / ".git").mkdir()
        self.settings.codex_sessions_root.mkdir(parents=True)
        session_file = self.settings.codex_sessions_root / "repo.jsonl"
        session_file.write_text(
            '{"type":"session_meta","payload":{"cwd":"%s","id":"session-2"}}\n'
            % str(repo).replace("\\", "\\\\"),
            encoding="utf-8",
        )

        with patch.object(self.service, "_find_git_root", return_value=repo):
            candidates = self.service._discover_codex_sessions()

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][0], "codex_session")
        self.assertEqual(candidates[0][1], "project-radar")


if __name__ == "__main__":
    unittest.main()
