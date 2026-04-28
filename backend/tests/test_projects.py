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

    def test_list_recent_releases_uses_cached_snapshots(self) -> None:
        self.service = ProjectService(self.db, self.settings)
        now = datetime.now(timezone.utc)
        success_at = (now - timedelta(minutes=5)).isoformat()
        next_due_at = (now + timedelta(minutes=10)).isoformat()
        self.service._store_release_snapshots(
            [
                {
                    "project_id": 1,
                    "provider": "netlify",
                    "environment": "production",
                    "service_name": "radar-site",
                    "management_url": "https://app.netlify.com/sites/radar-site",
                    "deploy_id": "dep-1",
                    "state": "finished",
                    "raw_state": "ready",
                    "updated_at": "2026-04-26T23:00:00Z",
                    "url": "https://radar-site.netlify.app",
                    "summary": "production",
                    "is_current": True,
                    "details": {"provider": "netlify"},
                    "actions": [{"id": "restore_previous_deploy"}],
                    "release_health": "current",
                    "health_reason": "This is the active release.",
                    "release_sync_status": "live",
                    "release_sync_at": success_at,
                    "next_sync_due_at": next_due_at,
                    "release_sync_reason": "Release metadata is freshly synced.",
                }
            ]
        )
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE sync_state
                SET last_success_at = ?, last_error_at = NULL, last_error_summary = NULL
                WHERE source = 'deploy'
                """,
                (success_at,),
            )
            conn.execute(
                """
                INSERT INTO projects (id, display_name, primary_local_path, remote_url, default_branch, owner, status, source_confidence, created_at, updated_at)
                VALUES (1, 'Radar', '', '', '', '', 'confirmed', 1.0, '2026-04-26T00:00:00Z', '2026-04-26T00:00:00Z')
                """
            )
            conn.commit()

        with patch.object(self.service, "_collect_recent_releases_live") as live_collector:
            result = self.service.list_recent_releases(limit=10)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["deploy_id"], "dep-1")
        self.assertEqual(result[0]["release_data_mode"], "synced-cache")
        live_collector.assert_not_called()

    def test_list_recent_releases_marks_cached_fallback_when_sync_failed(self) -> None:
        self.service = ProjectService(self.db, self.settings)
        now = datetime.now(timezone.utc)
        prior_success_at = (now - timedelta(minutes=30)).isoformat()
        error_at = (now - timedelta(minutes=1)).isoformat()
        self.service._store_release_snapshots(
            [
                {
                    "project_id": 1,
                    "provider": "render",
                    "environment": "production",
                    "service_name": "radar-api",
                    "management_url": "https://dashboard.render.com/web/srv-123",
                    "deploy_id": "dep-2",
                    "state": "failed",
                    "raw_state": "build_failed",
                    "updated_at": "2026-04-26T23:00:00Z",
                    "url": "https://radar-api.onrender.com",
                    "summary": "failed deploy",
                    "is_current": False,
                    "details": {"provider": "render"},
                    "actions": [],
                    "release_health": "risky",
                    "health_reason": "Deploy failed.",
                    "release_sync_status": "live",
                    "release_sync_at": prior_success_at,
                    "next_sync_due_at": (now - timedelta(minutes=15)).isoformat(),
                    "release_sync_reason": "Release metadata is freshly synced.",
                }
            ]
        )
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE sync_state
                SET last_success_at = ?,
                    last_error_at = ?,
                    last_error_summary = 'provider timeout'
                WHERE source = 'deploy'
                """,
                (prior_success_at, error_at),
            )
            conn.execute(
                """
                INSERT INTO projects (id, display_name, primary_local_path, remote_url, default_branch, owner, status, source_confidence, created_at, updated_at)
                VALUES (1, 'Radar', '', '', '', '', 'confirmed', 1.0, '2026-04-26T00:00:00Z', '2026-04-26T00:00:00Z')
                """
            )
            conn.commit()

        result = self.service.list_recent_releases(limit=10)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["release_data_mode"], "fallback-cache")
        self.assertEqual(result[0]["release_data_reason"], "provider timeout")

    def test_list_recent_releases_marks_live_provider_when_not_cached(self) -> None:
        self.service = ProjectService(self.db, self.settings)
        with patch.object(
            self.service,
            "_collect_recent_releases_live",
            return_value=[
                {
                    "project_id": 1,
                    "display_name": "Radar",
                    "provider": "netlify",
                    "environment": "production",
                    "service_name": "radar-site",
                    "management_url": "https://app.netlify.com/sites/radar-site",
                    "deploy_id": "dep-live",
                    "state": "finished",
                    "raw_state": "ready",
                    "updated_at": "2026-04-26T23:10:00Z",
                    "url": "https://radar-site.netlify.app",
                    "summary": "production",
                    "is_current": True,
                    "details": {"provider": "netlify"},
                    "actions": [],
                    "release_health": "current",
                    "health_reason": "This is the active release.",
                    "release_sync_status": "live",
                    "release_sync_at": "2026-04-26T23:10:00Z",
                    "next_sync_due_at": "2026-04-26T23:25:00Z",
                    "release_sync_reason": "Release metadata is freshly synced.",
                }
            ],
        ):
            result = self.service.list_recent_releases(limit=10)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["release_data_mode"], "live-provider")
        self.assertIn("Loaded directly from provider APIs", result[0]["release_data_reason"])

    def test_store_release_snapshots_replaces_matching_release_key(self) -> None:
        self.service = ProjectService(self.db, self.settings)
        snapshot = {
            "project_id": 1,
            "provider": "netlify",
            "environment": "production",
            "service_name": "radar-site",
            "management_url": "https://app.netlify.com/sites/radar-site",
            "deploy_id": "dep-1",
            "state": "finished",
            "raw_state": "ready",
            "updated_at": "2026-04-26T23:00:00Z",
            "url": "https://radar-site.netlify.app",
            "summary": "production",
            "is_current": True,
            "details": {"provider": "netlify"},
            "actions": [],
            "release_health": "current",
            "health_reason": "This is the active release.",
            "release_sync_status": "live",
            "release_sync_at": "2026-04-26T23:05:00Z",
            "next_sync_due_at": "2026-04-26T23:20:00Z",
            "release_sync_reason": "Release metadata is freshly synced.",
        }
        self.service._store_release_snapshots([snapshot])
        updated = dict(snapshot)
        updated["summary"] = "updated production"
        self.service._store_release_snapshots([updated])

        with self.db.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM release_snapshots").fetchone()
            summary = conn.execute("SELECT summary FROM release_snapshots").fetchone()["summary"]

        self.assertEqual(int(row["count"]), 1)
        self.assertEqual(summary, "updated production")

    def test_prune_release_snapshots_removes_old_rows(self) -> None:
        self.service = ProjectService(self.db, self.settings)
        old_snapshot = {
            "project_id": 1,
            "provider": "netlify",
            "environment": "production",
            "service_name": "radar-site",
            "management_url": "",
            "deploy_id": "old-dep",
            "state": "finished",
            "raw_state": "ready",
            "updated_at": "2020-01-01T00:00:00+00:00",
            "url": "",
            "summary": "old",
            "is_current": False,
            "details": {},
            "actions": [],
            "release_health": "stale",
            "health_reason": "old",
            "release_sync_status": "stale",
            "release_sync_at": "",
            "next_sync_due_at": "",
            "release_sync_reason": "",
        }
        new_snapshot = dict(old_snapshot)
        new_snapshot["deploy_id"] = "new-dep"
        new_snapshot["updated_at"] = "2026-04-26T23:00:00+00:00"
        new_snapshot["summary"] = "new"

        self.service._store_release_snapshots([old_snapshot, new_snapshot])

        with self.db.connect() as conn:
            rows = conn.execute("SELECT deploy_id FROM release_snapshots ORDER BY deploy_id").fetchall()

        self.assertEqual([row["deploy_id"] for row in rows], ["new-dep"])

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
            "_collect_recent_releases_live",
            return_value=[{"deploy_id": "dep-1"}],
        ), patch.object(
            self.service,
            "_store_release_snapshots",
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


class ProjectServiceSessionTests(unittest.TestCase):
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

    def test_sync_codex_activity_attaches_current_session_to_project(self) -> None:
        repo = self.base_dir / "project-radar"
        repo.mkdir()
        session_dir = self.settings.codex_sessions_root
        session_dir.mkdir(parents=True)
        session_file = session_dir / "session-1.jsonl"
        session_file.write_text(
            '{"payload":{"cwd":"%s","id":"11111111-1111-1111-1111-111111111111"}}\n'
            % str(repo).replace("\\", "\\\\"),
            encoding="utf-8",
        )

        with self.db.connect() as conn:
            now = "2026-04-26T00:00:00+00:00"
            conn.execute(
                """
                INSERT INTO projects
                (id, display_name, primary_local_path, remote_url, default_branch, owner, status, source_confidence, created_at, updated_at)
                VALUES (1, 'project-radar', ?, '', 'main', 'local', 'confirmed', 1.0, ?, ?)
                """,
                (str(repo), now, now),
            )
            conn.execute(
                """
                INSERT INTO project_aliases (project_id, alias_type, alias_value, confidence)
                VALUES (1, 'repo_path', ?, 1.0)
                """,
                (str(repo),),
            )
            conn.commit()

        with patch.object(self.service, "_find_git_root", return_value=repo), patch.object(
            self.service,
            "_read_git_branch",
            return_value="main",
        ):
            result = self.service.sync_codex_activity()

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["sessions"], 1)
        project = self.service.get_project(1)
        self.assertIsNotNone(project)
        current_sessions = project["current_sessions"]
        self.assertEqual(len(current_sessions), 1)
        self.assertEqual(current_sessions[0]["source"], "codex")
        self.assertEqual(current_sessions[0]["branch"], "main")
        self.assertTrue(current_sessions[0]["is_current"])
        self.assertIn("codex resume", current_sessions[0]["resume_command"])

    def test_resume_project_session_launches_powershell(self) -> None:
        repo = self.base_dir / "project-radar"
        repo.mkdir()

        with self.db.connect() as conn:
            now = "2026-04-26T00:00:00+00:00"
            conn.execute(
                """
                INSERT INTO projects
                (id, display_name, primary_local_path, remote_url, default_branch, owner, status, source_confidence, created_at, updated_at)
                VALUES (1, 'project-radar', ?, '', 'main', 'local', 'confirmed', 1.0, ?, ?)
                """,
                (str(repo), now, now),
            )
            conn.execute(
                """
                INSERT INTO project_sessions
                (id, project_id, source, session_id, session_path, cwd, repo_path, branch, status,
                 last_activity_at, summary, resume_command, open_command, is_current, created_at, updated_at)
                VALUES (
                    9, 1, 'codex', 'session-123', ?, ?, ?, 'main', 'current',
                    ?, 'Codex current session', ?, ?, 1, ?, ?
                )
                """,
                (
                    str(self.base_dir / "codex" / "session-123.jsonl"),
                    str(repo),
                    str(repo),
                    now,
                    "codex resume 'session-123' -C '%s'" % str(repo).replace("'", "''"),
                    str(self.base_dir / "codex" / "session-123.jsonl"),
                    now,
                    now,
                ),
            )
            conn.commit()

        with patch("app.services.projects.subprocess.Popen") as popen:
            result = self.service.resume_project_session(1, 9)

        self.assertEqual(result["status"], "launched")
        self.assertEqual(result["session_id"], "session-123")
        popen.assert_called_once()

    def test_launch_project_codex_opens_terminal_in_project_path(self) -> None:
        repo = self.base_dir / "project-radar"
        repo.mkdir()

        with self.db.connect() as conn:
            now = "2026-04-26T00:00:00+00:00"
            conn.execute(
                """
                INSERT INTO projects
                (id, display_name, primary_local_path, remote_url, default_branch, owner, status, source_confidence, created_at, updated_at)
                VALUES (1, 'project-radar', ?, '', 'main', 'local', 'confirmed', 1.0, ?, ?)
                """,
                (str(repo), now, now),
            )
            conn.commit()

        with patch("app.services.projects.shutil.which", return_value="codex"), patch(
            "app.services.projects.subprocess.Popen"
        ) as popen:
            result = self.service.launch_project_codex(1)

        self.assertEqual(result["status"], "launched")
        self.assertIn("codex -C", result["command"])
        popen.assert_called_once()

    def test_launch_project_openclaw_opens_terminal_in_project_path(self) -> None:
        repo = self.base_dir / "project-radar"
        repo.mkdir()

        with self.db.connect() as conn:
            now = "2026-04-26T00:00:00+00:00"
            conn.execute(
                """
                INSERT INTO projects
                (id, display_name, primary_local_path, remote_url, default_branch, owner, status, source_confidence, created_at, updated_at)
                VALUES (1, 'project-radar', ?, '', 'main', 'local', 'confirmed', 1.0, ?, ?)
                """,
                (str(repo), now, now),
            )
            conn.commit()

        with patch("app.services.projects.shutil.which", return_value="openclaw"), patch(
            "app.services.projects.subprocess.Popen"
        ) as popen:
            result = self.service.launch_project_openclaw(1)

        self.assertEqual(result["status"], "launched")
        self.assertIn("openclaw --cwd", result["command"])
        popen.assert_called_once()

    def test_create_project_infers_git_metadata(self) -> None:
        repo = self.base_dir / "project-radar"
        repo.mkdir()
        (repo / ".git").mkdir()

        with patch.object(
            self.service,
            "_git_value",
            side_effect=["https://github.com/acme/radar.git", "main", "main", "2026-04-26T00:00:00Z", "origin", "https://github.com/acme/radar.git"],
        ), patch.object(self.service, "_git_has_uncommitted_changes", return_value=False):
            result = self.service.create_project(display_name="", primary_local_path=str(repo))

        self.assertEqual(result["status"], "created")
        project = self.service.get_project(int(result["project_id"]))
        self.assertEqual(project["display_name"], "project-radar")
        self.assertEqual(project["remote_url"], "https://github.com/acme/radar.git")
        self.assertEqual(project["default_branch"], "main")

    def test_delete_project_removes_records_and_reopens_candidate(self) -> None:
        repo = self.base_dir / "project-radar"
        repo.mkdir()
        with self.db.connect() as conn:
            now = "2026-04-26T00:00:00+00:00"
            conn.execute(
                """
                INSERT INTO projects
                (id, display_name, primary_local_path, remote_url, default_branch, owner, status, source_confidence, created_at, updated_at)
                VALUES (1, 'project-radar', ?, 'https://github.com/acme/radar.git', 'main', 'local', 'confirmed', 1.0, ?, ?)
                """,
                (str(repo), now, now),
            )
            conn.execute(
                """
                INSERT INTO project_aliases (project_id, alias_type, alias_value, confidence)
                VALUES (1, 'repo_path', ?, 1.0)
                """,
                (str(repo),),
            )
            conn.execute(
                """
                INSERT INTO discovery_candidates
                (id, candidate_type, display_name, source, evidence_json, confidence, review_status, created_at)
                VALUES
                (7, 'git_repo', 'project-radar', 'git_scan', ?, 0.95, 'confirmed', ?)
                """,
                ('{"repo_path":"%s","remote_url":"https://github.com/acme/radar.git"}' % str(repo).replace("\\", "\\\\"), now),
            )
            conn.commit()

        result = self.service.delete_project(1)

        self.assertEqual(result["status"], "deleted")
        self.assertIsNone(self.service.get_project(1))
        with self.db.connect() as conn:
            row = conn.execute("SELECT review_status FROM discovery_candidates WHERE id = 7").fetchone()
        self.assertEqual(row["review_status"], "pending")


if __name__ == "__main__":
    unittest.main()
