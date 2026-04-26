from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.db.database import Database
from app.services.projects import ProjectService


class ProjectServiceDeploymentTests(unittest.TestCase):
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

    def test_enriches_vercel_deployment_from_api(self) -> None:
        repo = self.base_dir / "vercel-app"
        (repo / ".vercel").mkdir(parents=True)
        (repo / ".vercel" / "project.json").write_text(
            '{"projectId":"prj_123","orgId":"team_456","projectName":"radar-web"}',
            encoding="utf-8",
        )
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
            vercel_token="vercel-token",
            netlify_token="",
            render_token="",
        )
        self.service = ProjectService(self.db, self.settings)

        with patch.object(
            self.service,
            "_http_json",
            return_value={
                "deployments": [
                    {
                        "name": "radar-web",
                        "url": "radar-web.vercel.app",
                        "readyState": "READY",
                        "createdAt": 1714147200000,
                        "inspectorUrl": "https://vercel.com/acme/radar-web/deployments/123",
                        "checksConclusion": "succeeded",
                    }
                ]
            },
        ):
            deployments = self.service._enrich_deployments(
                project={"primary_local_path": str(repo)},
                deployments=[
                    {
                        "provider": "vercel",
                        "environment": "production",
                        "state": "available",
                        "management_url": "https://vercel.com/dashboard",
                    }
                ],
            )

        target = deployments[0]
        self.assertEqual(target["state"], "finished")
        self.assertEqual(target["service_name"], "radar-web")
        self.assertEqual(target["url"], "https://radar-web.vercel.app")
        self.assertEqual(target["management_url"], "https://vercel.com/acme/radar-web/deployments/123")
        self.assertEqual(target["live_source"], "vercel_api")

    def test_enriches_netlify_deployment_from_api(self) -> None:
        repo = self.base_dir / "netlify-app"
        (repo / ".netlify").mkdir(parents=True)
        (repo / ".netlify" / "state.json").write_text(
            '{"siteId":"site-123"}',
            encoding="utf-8",
        )
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
            netlify_token="netlify-token",
            render_token="",
        )
        self.service = ProjectService(self.db, self.settings)

        with patch.object(
            self.service,
            "_http_json",
            return_value=[
                {
                    "name": "radar-site",
                    "state": "ready",
                    "updated_at": "2026-04-26T22:00:00Z",
                    "deploy_url": "https://radar-site.netlify.app",
                    "admin_url": "https://app.netlify.com/sites/radar-site",
                    "context": "production",
                }
            ],
        ):
            deployments = self.service._enrich_deployments(
                project={"primary_local_path": str(repo)},
                deployments=[
                    {
                        "provider": "netlify",
                        "environment": "production",
                        "state": "manual",
                        "management_url": "https://app.netlify.com/",
                    }
                ],
            )

        target = deployments[0]
        self.assertEqual(target["state"], "finished")
        self.assertEqual(target["service_name"], "radar-site")
        self.assertEqual(target["url"], "https://radar-site.netlify.app")
        self.assertEqual(target["management_url"], "https://app.netlify.com/sites/radar-site")
        self.assertEqual(target["live_source"], "netlify_api")

    def test_deployment_api_failure_falls_back_to_reason(self) -> None:
        repo = self.base_dir / "vercel-failure"
        (repo / ".vercel").mkdir(parents=True)
        (repo / ".vercel" / "project.json").write_text(
            '{"projectId":"prj_123"}',
            encoding="utf-8",
        )
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
            vercel_token="vercel-token",
            netlify_token="",
            render_token="",
        )
        self.service = ProjectService(self.db, self.settings)

        with patch.object(self.service, "_http_json", side_effect=RuntimeError("bad token")):
            deployments = self.service._enrich_deployments(
                project={"primary_local_path": str(repo)},
                deployments=[
                    {
                        "provider": "vercel",
                        "environment": "production",
                        "state": "available",
                        "availability_reason": "Runnable locally via vercel --prod.",
                    }
                ],
            )

        target = deployments[0]
        self.assertEqual(target["state"], "available")
        self.assertIn("metadata is unavailable", target["availability_reason"])
        self.assertIn("bad token", target["availability_reason"])

    def test_perform_render_trigger_action(self) -> None:
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
            render_token="render-token",
        )
        self.service = ProjectService(self.db, self.settings)

        with patch.object(
            self.service,
            "get_project",
            return_value={"deployments": [{"provider": "render", "service_id": "srv-123"}]},
        ), patch.object(
            self.service,
            "_http_json",
            return_value={"id": "dep-123"},
        ), patch.object(self.service, "_mark_deploy_state") as mark_state:
            result = self.service.perform_deployment_action(5, "render", "trigger_api_deploy")

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["deploy_id"], "dep-123")
        mark_state.assert_called_once_with(5, provider="render", state="queued")

    def test_perform_netlify_restore_action(self) -> None:
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
            netlify_token="netlify-token",
            render_token="",
        )
        self.service = ProjectService(self.db, self.settings)

        with patch.object(
            self.service,
            "get_project",
            return_value={"deployments": [{"provider": "netlify", "site_id": "site-123", "deploy_id": "current-1"}]},
        ), patch.object(
            self.service,
            "_http_json",
            side_effect=[
                [
                    {"id": "current-1", "state": "current"},
                    {"id": "old-2", "state": "old"},
                ],
                {"id": "old-2"},
            ],
        ), patch.object(self.service, "_mark_deploy_state") as mark_state:
            result = self.service.perform_deployment_action(7, "netlify", "restore_previous_deploy")

        self.assertEqual(result["status"], "running")
        self.assertEqual(result["deploy_id"], "old-2")
        mark_state.assert_called_once_with(7, provider="netlify", state="running")

    def test_perform_netlify_restore_action_with_target_deploy(self) -> None:
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
            netlify_token="netlify-token",
            render_token="",
        )
        self.service = ProjectService(self.db, self.settings)

        with patch.object(
            self.service,
            "get_project",
            return_value={"deployments": [{"provider": "netlify", "site_id": "site-123", "deploy_id": "current-1"}]},
        ), patch.object(
            self.service,
            "_http_json",
            side_effect=[
                [
                    {"id": "current-1", "state": "current"},
                    {"id": "old-2", "state": "old"},
                    {"id": "old-3", "state": "old"},
                ],
                {"id": "old-3"},
            ],
        ), patch.object(self.service, "_mark_deploy_state") as mark_state:
            result = self.service.perform_deployment_action(
                7,
                "netlify",
                "restore_previous_deploy",
                {"deploy_id": "old-3"},
            )

        self.assertEqual(result["status"], "running")
        self.assertEqual(result["deploy_id"], "old-3")
        mark_state.assert_called_once_with(7, provider="netlify", state="running")

    def test_list_netlify_deployment_history(self) -> None:
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
            netlify_token="netlify-token",
            render_token="",
        )
        self.service = ProjectService(self.db, self.settings)

        with patch.object(
            self.service,
            "get_project",
            return_value={"deployments": [{"provider": "netlify", "site_id": "site-123", "deploy_id": "current-1"}]},
        ), patch.object(
            self.service,
            "_http_json",
            return_value=[
                {"id": "current-1", "state": "current", "updated_at": "2026-04-26T22:00:00Z", "deploy_url": "https://current", "context": "production"},
                {"id": "old-2", "state": "old", "updated_at": "2026-04-25T22:00:00Z", "deploy_url": "https://old", "context": "production"},
            ],
        ):
            result = self.service.list_deployment_history(7, "netlify", limit=10)

        self.assertEqual(result["provider"], "netlify")
        self.assertEqual(len(result["items"]), 2)
        self.assertTrue(result["items"][0]["is_current"])
        self.assertEqual(result["items"][1]["actions"][0]["id"], "restore_previous_deploy")
        self.assertIn("safety_note", result["items"][1]["details"])

    def test_list_vercel_deployment_history_includes_details(self) -> None:
        repo = self.base_dir / "vercel-history"
        (repo / ".vercel").mkdir(parents=True)
        (repo / ".vercel" / "project.json").write_text(
            '{"projectId":"prj_123","orgId":"team_456"}',
            encoding="utf-8",
        )
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
            vercel_token="vercel-token",
            netlify_token="",
            render_token="",
        )
        self.service = ProjectService(self.db, self.settings)

        with patch.object(
            self.service,
            "get_project",
            return_value={
                "primary_local_path": str(repo),
                "deployments": [{"provider": "vercel", "environment": "production", "deploy_id": "dep-current"}],
            },
        ), patch.object(
            self.service,
            "_http_json",
            return_value={
                "deployments": [
                    {
                        "uid": "dep-current",
                        "readyState": "READY",
                        "createdAt": 1714147200000,
                        "ready": 1714147800000,
                        "url": "radar.vercel.app",
                        "checksConclusion": "succeeded",
                        "target": "production",
                        "inspectorUrl": "https://vercel.com/acme/radar/deployments/dep-current",
                    }
                ]
            },
        ):
            result = self.service.list_deployment_history(9, "vercel", limit=10)

        self.assertEqual(result["provider"], "vercel")
        self.assertEqual(result["items"][0]["details"]["checks"], "succeeded")
        self.assertIn("safety_note", result["items"][0]["details"])

    def test_list_recent_releases_aggregates_projects(self) -> None:
        self.service = ProjectService(self.db, self.settings)

        with patch.object(
            self.service,
            "list_projects",
            return_value=[
                {
                    "id": 1,
                    "display_name": "Radar",
                    "deployments": [
                        {
                            "provider": "netlify",
                            "environment": "production",
                            "service_name": "radar-site",
                            "management_url": "https://app.netlify.com/sites/radar-site",
                            "history_supported": True,
                        }
                    ],
                },
                {
                    "id": 2,
                    "display_name": "Control",
                    "deployments": [
                        {
                            "provider": "render",
                            "environment": "production",
                            "service_name": "control-web",
                            "management_url": "https://dashboard.render.com/web/srv-1",
                            "history_supported": True,
                        }
                    ],
                },
            ],
        ), patch.object(
            self.service,
            "list_deployment_history",
            side_effect=[
                {
                    "items": [
                        {
                            "deploy_id": "n-1",
                            "state": "finished",
                            "raw_state": "ready",
                            "updated_at": "2026-04-26T23:00:00Z",
                            "url": "https://radar-site.netlify.app",
                            "summary": "production",
                            "is_current": True,
                            "details": {"provider": "netlify"},
                            "actions": [],
                        }
                    ]
                },
                {
                    "items": [
                        {
                            "deploy_id": "r-1",
                            "state": "running",
                            "raw_state": "build_in_progress",
                            "updated_at": "2026-04-26T22:30:00Z",
                            "url": "",
                            "summary": "deploy",
                            "is_current": True,
                            "details": {"provider": "render"},
                            "actions": [],
                        }
                    ]
                },
            ],
        ):
            result = self.service.list_recent_releases(limit=10)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["project_id"], 1)
        self.assertEqual(result[0]["deploy_id"], "n-1")
        self.assertEqual(result[1]["project_id"], 2)
        self.assertEqual(result[0]["release_health"], "current")

    def test_release_health_classification(self) -> None:
        current = self.service._release_health({"state": "finished", "is_current": True, "details": {}})
        rollbackable = self.service._release_health(
            {
                "state": "finished",
                "is_current": False,
                "actions": [{"id": "restore_previous_deploy"}],
                "details": {},
                "updated_at": "2026-04-20T00:00:00+00:00",
            }
        )
        risky = self.service._release_health(
            {
                "state": "failed",
                "is_current": False,
                "details": {},
            }
        )

        self.assertEqual(current["health"], "current")
        self.assertEqual(rollbackable["health"], "rollbackable")
        self.assertEqual(risky["health"], "risky")

    def test_release_sync_status_classification(self) -> None:
        now = datetime.now(timezone.utc)
        live = self.service._release_sync_status(
            {"last_success_at": (now - timedelta(minutes=5)).isoformat(), "last_error_at": None, "last_error_summary": None}
        )
        stale = self.service._release_sync_status(
            {"last_success_at": (now - timedelta(minutes=90)).isoformat(), "last_error_at": None, "last_error_summary": None}
        )
        error = self.service._release_sync_status(
            {
                "last_success_at": (now - timedelta(minutes=30)).isoformat(),
                "last_error_at": (now - timedelta(minutes=1)).isoformat(),
                "last_error_summary": "provider timeout",
            }
        )

        self.assertEqual(live["status"], "live")
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(error["status"], "error")

    def test_sync_release_metadata_returns_sync_status(self) -> None:
        self.service = ProjectService(self.db, self.settings)
        with patch.object(
            self.service,
            "list_recent_releases",
            return_value=[{"deploy_id": "dep-1"}],
        ), patch.object(
            self.service,
            "release_sync_status",
            return_value={"status": "live", "reason": "fresh"},
        ):
            result = self.service.sync_release_metadata(limit=10)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["releases"], 1)
        self.assertEqual(result["release_sync"]["status"], "live")

    def test_background_release_sync_lifecycle(self) -> None:
        self.service = ProjectService(self.db, self.settings)
        with patch.object(self.service, "_background_release_sync_loop") as loop:
            self.service.start_background_release_sync()
            self.service.stop_background_release_sync()

        loop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
