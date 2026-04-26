from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.config import Settings
from app.db.database import Database
from app.services.projects import ProjectService


class ProjectServiceDeploymentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.db = Database(self.base_dir / "project_radar.db")
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
        )
        self.service = ProjectService(self.db, self.settings)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_detects_fly_management_url_and_service_name(self) -> None:
        repo = self.base_dir / "fly-app"
        repo.mkdir()
        (repo / "fly.toml").write_text('app = "radar-app"\n', encoding="utf-8")

        deployments = self.service._detect_deploy_targets(str(repo))

        self.assertEqual(len(deployments), 1)
        target = deployments[0]
        self.assertEqual(target["provider"], "fly")
        self.assertEqual(target["service_name"], "radar-app")
        self.assertEqual(target["management_url"], "https://fly.io/apps/radar-app")
        self.assertIn("configured", target["availability_reason"])

    def test_detects_render_management_console(self) -> None:
        repo = self.base_dir / "render-app"
        repo.mkdir()
        (repo / "render.yaml").write_text("services:\n  - type: web\n    name: radar-web\n", encoding="utf-8")

        deployments = self.service._detect_deploy_targets(str(repo))

        self.assertEqual(len(deployments), 1)
        target = deployments[0]
        self.assertEqual(target["provider"], "render")
        self.assertEqual(target["service_name"], "radar-web")
        self.assertEqual(target["management_url"], "https://dashboard.render.com/")
        self.assertEqual(target["state"], "manual")


if __name__ == "__main__":
    unittest.main()
