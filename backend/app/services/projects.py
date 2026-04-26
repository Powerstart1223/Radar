"""Project and discovery review services."""

from __future__ import annotations

import json
import subprocess
import shutil
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import Settings
from app.db.database import Database, utc_now_iso

STALE_REPO_HOURS = 72
DEPLOY_TARGET_SPECS = (
    {
        "provider": "vercel",
        "markers": ("vercel.json", ".vercel/project.json"),
        "command": "vercel --prod",
        "environment": "production",
    },
    {
        "provider": "netlify",
        "markers": ("netlify.toml",),
        "command": "netlify deploy --prod",
        "environment": "production",
    },
    {
        "provider": "fly",
        "markers": ("fly.toml",),
        "command": "fly deploy",
        "environment": "production",
    },
    {
        "provider": "railway",
        "markers": ("railway.json",),
        "command": "railway up",
        "environment": "production",
    },
    {
        "provider": "render",
        "markers": ("render.yaml", "render.yml"),
        "command": "",
        "environment": "production",
    },
)


class ProjectService:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    def list_projects(self) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.display_name, p.primary_local_path, p.remote_url, p.default_branch,
                       p.owner, p.status, p.source_confidence, p.updated_at,
                       rs.branch, rs.last_commit_at, rs.has_uncommitted_changes, rs.synced_at AS repo_synced_at,
                       prs.state AS pr_state, prs.checks_state
                FROM projects p
                LEFT JOIN repo_snapshots rs ON rs.project_id = p.id
                LEFT JOIN pull_request_snapshots prs ON prs.project_id = p.id
                ORDER BY p.updated_at DESC, p.id DESC
                """
            ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            attention = self._derive_attention(item, self._recent_runs_for_project(int(item["id"]), limit=5))
            item["attention"] = attention
            item["attention_count"] = len(attention)
            item["attention_severity"] = self._highest_attention_severity(attention)
            item["deployments"] = self._merge_deployments(
                saved_rows=self._load_deployments_for_project(int(item["id"])),
                detected_targets=self._detect_deploy_targets(item.get("primary_local_path")),
            )
        return items

    def get_project(self, project_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT id, display_name, primary_local_path, remote_url, default_branch,
                       owner, status, source_confidence, created_at, updated_at
                FROM projects
                WHERE id = ?
                """,
                (project_id,),
            ).fetchone()
            if row is None:
                return None

            project = dict(row)
            alias_rows = conn.execute(
                """
                SELECT alias_type, alias_value, confidence
                FROM project_aliases
                WHERE project_id = ?
                ORDER BY confidence DESC, id DESC
                """,
                (project_id,),
            ).fetchall()
            repo_snapshot = conn.execute(
                """
                SELECT branch, has_uncommitted_changes, last_commit_at, remote_name, synced_at
                FROM repo_snapshots
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
            related_candidates = conn.execute(
                """
                SELECT id, candidate_type, display_name, source, confidence, review_status, created_at
                FROM discovery_candidates
                WHERE id IN (
                    SELECT DISTINCT dc.id
                    FROM discovery_candidates dc
                    JOIN project_aliases pa
                      ON pa.project_id = ?
                     AND (
                        (pa.alias_type = 'repo_path' AND json_extract(dc.evidence_json, '$.repo_path') = pa.alias_value)
                        OR (pa.alias_type = 'cwd' AND json_extract(dc.evidence_json, '$.cwd') = pa.alias_value)
                        OR (pa.alias_type = 'remote_url' AND json_extract(dc.evidence_json, '$.remote_url') = pa.alias_value)
                     )
                )
                ORDER BY created_at DESC, id DESC
                LIMIT 10
                """,
                (project_id,),
            ).fetchall()
            recent_runs = conn.execute(
                """
                SELECT id, agent_type, skill_name, cwd, command, status, started_at, finished_at,
                       output_summary, artifact_dir, log_path
                FROM agent_runs
                WHERE project_id = ?
                ORDER BY started_at DESC, id DESC
                LIMIT 10
                """,
                (project_id,),
            ).fetchall()
            recent_events = conn.execute(
                """
                SELECT source, event_type, occurred_at, session_id, summary, raw_ref
                FROM agent_events
                WHERE project_id = ?
                ORDER BY occurred_at DESC, id DESC
                LIMIT 10
                """,
                (project_id,),
            ).fetchall()

        project["aliases"] = [dict(alias) for alias in alias_rows]
        project["repo_snapshot"] = dict(repo_snapshot) if repo_snapshot else None
        project["related_candidates"] = [dict(candidate) for candidate in related_candidates]
        project["recent_runs"] = [dict(run) for run in recent_runs]
        project["recent_events"] = [dict(event) for event in recent_events]
        project["deployments"] = self._merge_deployments(
            saved_rows=self._load_deployments_for_project(project_id),
            detected_targets=self._detect_deploy_targets(project.get("primary_local_path")),
        )
        project["attention"] = self._derive_attention(project, project["recent_runs"])
        project["attention_severity"] = self._highest_attention_severity(project["attention"])
        return project

    def list_attention_queue(self) -> list[dict]:
        queue = []
        for project in self.list_projects():
            for issue in project.get("attention", []):
                queue.append(
                    {
                        "project_id": project["id"],
                        "display_name": project["display_name"],
                        "severity": issue["severity"],
                        "type": issue["type"],
                        "title": issue["title"],
                        "detail": issue["detail"],
                    }
                )
        return sorted(queue, key=self._attention_sort_key)

    def list_recent_activity(self, *, limit: int = 20) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT ae.project_id, ae.source, ae.event_type, ae.occurred_at, ae.session_id,
                       ae.summary, ae.raw_ref, p.display_name
                FROM agent_events ae
                LEFT JOIN projects p ON p.id = ae.project_id
                ORDER BY ae.occurred_at DESC, ae.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def refresh_project_repo(self, project_id: int) -> dict:
        with self.db.connect() as conn:
            project = conn.execute(
                """
                SELECT id, display_name, primary_local_path
                FROM projects
                WHERE id = ?
                """,
                (project_id,),
            ).fetchone()
            if project is None:
                raise ValueError("Project not found")

            refreshed = self._refresh_project_metadata(conn, project_id)
            conn.commit()

        if not refreshed:
            return {
                "project_id": project_id,
                "status": "skipped",
                "reason": "No valid git repository path found for project.",
            }
        return {"project_id": project_id, "status": "refreshed"}

    def refresh_all_project_repos(self) -> dict:
        refreshed = 0
        skipped = 0
        with self.db.connect() as conn:
            rows = conn.execute("SELECT id FROM projects ORDER BY id").fetchall()
            for row in rows:
                if self._refresh_project_metadata(conn, int(row["id"])):
                    refreshed += 1
                else:
                    skipped += 1
            conn.commit()
        return {"status": "completed", "refreshed": refreshed, "skipped": skipped}

    def prepare_deploy_run(self, project_id: int) -> dict:
        project = self.get_project(project_id)
        if project is None:
            raise ValueError("Project not found")

        deployments = project.get("deployments") or []
        target = next((item for item in deployments if item.get("runnable")), None)
        if target is None:
            raise ValueError("No runnable deployment target is available for project")

        provider = str(target["provider"])
        command = str(target["command"])
        cwd = str(project.get("primary_local_path") or "")
        if not cwd:
            raise ValueError("Project has no local path for deployment")

        self._mark_deploy_state(project_id, provider=provider, state="queued")
        return {
            "project_id": project_id,
            "agent_type": "deploy",
            "skill_name": f"deploy:{provider}",
            "cwd": cwd,
        }

    def sync_codex_activity(self) -> dict:
        return self._sync_agent_activity(source="codex", sessions_root=self.settings.codex_sessions_root, glob_pattern="*.jsonl")

    def sync_openclaw_activity(self) -> dict:
        return self._sync_agent_activity(
            source="openclaw",
            sessions_root=self.settings.openclaw_sessions_root,
            glob_pattern="*.jsonl*",
        )

    def sync_github_pull_requests(self, project_id: int | None = None) -> dict:
        project_ids = [project_id] if project_id is not None else [item["id"] for item in self.list_projects()]
        synced = 0
        skipped = 0
        errors = 0
        for current_project_id in project_ids:
            result = self._sync_project_github(int(current_project_id))
            if result == "synced":
                synced += 1
            elif result == "skipped":
                skipped += 1
            else:
                errors += 1
        self._mark_sync_state(
            "github",
            success=errors == 0,
            error_summary=None if errors == 0 else f"{errors} project syncs failed",
        )
        return {"status": "completed", "synced": synced, "skipped": skipped, "errors": errors}

    def confirm_candidate(self, candidate_id: int, owner: str = "local") -> dict:
        with self.db.connect() as conn:
            candidate = conn.execute(
                """
                SELECT id, candidate_type, display_name, source, evidence_json, confidence, review_status
                FROM discovery_candidates
                WHERE id = ?
                """,
                (candidate_id,),
            ).fetchone()
            if candidate is None:
                raise ValueError("Candidate not found")
            if candidate["review_status"] != "pending":
                raise ValueError("Candidate is no longer pending")

            evidence = self._parse_evidence(candidate["evidence_json"])
            primary_local_path = evidence.get("repo_path") or evidence.get("cwd") or None
            remote_url = evidence.get("remote_url") or None
            default_branch = evidence.get("default_branch") or None

            existing = self._find_existing_project(conn, primary_local_path, remote_url)
            if existing is not None:
                self._attach_candidate_to_project(conn, candidate, evidence, int(existing["id"]))
                self._refresh_project_metadata(conn, int(existing["id"]))
                conn.commit()
                return {"project_id": int(existing["id"]), "status": "merged_existing"}

            now = utc_now_iso()
            cursor = conn.execute(
                """
                INSERT INTO projects
                (display_name, primary_local_path, remote_url, default_branch, owner, status, source_confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'confirmed', ?, ?, ?)
                """,
                (
                    candidate["display_name"],
                    primary_local_path,
                    remote_url,
                    default_branch,
                    owner,
                    float(candidate["confidence"]),
                    now,
                    now,
                ),
            )
            project_id = int(cursor.lastrowid)
            self._attach_candidate_to_project(conn, candidate, evidence, project_id)
            self._refresh_project_metadata(conn, project_id)
            conn.commit()
            return {"project_id": project_id, "status": "confirmed"}

    def merge_candidate(self, candidate_id: int, project_id: int) -> dict:
        with self.db.connect() as conn:
            candidate = conn.execute(
                """
                SELECT id, candidate_type, display_name, source, evidence_json, confidence, review_status
                FROM discovery_candidates
                WHERE id = ?
                """,
                (candidate_id,),
            ).fetchone()
            if candidate is None:
                raise ValueError("Candidate not found")
            if candidate["review_status"] != "pending":
                raise ValueError("Candidate is no longer pending")

            project = conn.execute(
                """
                SELECT id, source_confidence
                FROM projects
                WHERE id = ?
                """,
                (project_id,),
            ).fetchone()
            if project is None:
                raise ValueError("Project not found")

            evidence = self._parse_evidence(candidate["evidence_json"])
            self._attach_candidate_to_project(conn, candidate, evidence, project_id, merged=True)
            conn.execute(
                """
                UPDATE projects
                SET source_confidence = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    max(float(project["source_confidence"]), float(candidate["confidence"])),
                    utc_now_iso(),
                    project_id,
                ),
            )
            self._refresh_project_metadata(conn, project_id)
            conn.commit()
        return {"project_id": project_id, "status": "merged"}

    def _find_existing_project(self, conn, primary_local_path: str | None, remote_url: str | None):
        if primary_local_path:
            row = conn.execute(
                "SELECT id FROM projects WHERE primary_local_path = ?",
                (primary_local_path,),
            ).fetchone()
            if row is not None:
                return row
        if remote_url:
            row = conn.execute(
                "SELECT id FROM projects WHERE remote_url = ?",
                (remote_url,),
            ).fetchone()
            if row is not None:
                return row
        return None

    def _attach_candidate_to_project(
        self,
        conn,
        candidate,
        evidence: dict,
        project_id: int,
        *,
        merged: bool = False,
    ) -> None:
        alias_rows = []
        for alias_type, alias_value in (
            ("candidate_type", candidate["candidate_type"]),
            ("repo_path", evidence.get("repo_path")),
            ("cwd", evidence.get("cwd")),
            ("remote_url", evidence.get("remote_url")),
            ("session_file", evidence.get("session_file")),
        ):
            if alias_value:
                alias_rows.append((project_id, alias_type, str(alias_value), float(candidate["confidence"])))

        conn.executemany(
            """
            INSERT INTO project_aliases (project_id, alias_type, alias_value, confidence)
            SELECT ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM project_aliases
                WHERE project_id = ? AND alias_type = ? AND alias_value = ?
            )
            """,
            [
                (project_id, alias_type, alias_value, confidence, project_id, alias_type, alias_value)
                for project_id, alias_type, alias_value, confidence in alias_rows
            ],
        )
        conn.execute(
            """
            UPDATE discovery_candidates
            SET review_status = ?
            WHERE id = ?
            """,
            ("merged" if merged else "confirmed", candidate["id"]),
        )

    def _refresh_project_metadata(self, conn, project_id: int) -> bool:
        project = conn.execute(
            """
            SELECT id, primary_local_path, remote_url, default_branch
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()
        if project is None:
            return False

        local_path = self._resolve_primary_local_path(conn, project_id, project["primary_local_path"])
        if not local_path:
            return False

        repo_path = Path(local_path)
        if not (repo_path / ".git").exists():
            return False

        branch = self._git_value(repo_path, "symbolic-ref", "--short", "HEAD")
        last_commit_at = self._git_value(repo_path, "log", "-1", "--format=%cI")
        remote_name = self._git_value(repo_path, "remote")
        remote_name = remote_name.splitlines()[0].strip() if remote_name else ""
        remote_url = self._git_value(repo_path, "remote", "get-url", remote_name or "origin")
        has_uncommitted_changes = 1 if self._git_has_uncommitted_changes(repo_path) else 0
        synced_at = utc_now_iso()

        conn.execute(
            """
            UPDATE projects
            SET primary_local_path = ?,
                remote_url = COALESCE(NULLIF(remote_url, ''), ?),
                default_branch = COALESCE(NULLIF(default_branch, ''), ?),
                updated_at = ?
            WHERE id = ?
            """,
            (
                str(repo_path),
                remote_url or None,
                branch or None,
                synced_at,
                project_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO repo_snapshots
            (project_id, branch, has_uncommitted_changes, last_commit_at, remote_name, synced_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                branch = excluded.branch,
                has_uncommitted_changes = excluded.has_uncommitted_changes,
                last_commit_at = excluded.last_commit_at,
                remote_name = excluded.remote_name,
                synced_at = excluded.synced_at
            """,
            (
                project_id,
                branch or None,
                has_uncommitted_changes,
                last_commit_at or None,
                remote_name or None,
                synced_at,
            ),
        )
        self._refresh_project_deployments(conn, project_id, repo_path)
        return True

    def _resolve_primary_local_path(self, conn, project_id: int, existing_path: str | None) -> str | None:
        if existing_path:
            return existing_path

        alias_row = conn.execute(
            """
            SELECT alias_value
            FROM project_aliases
            WHERE project_id = ?
              AND alias_type IN ('repo_path', 'cwd')
              AND alias_value != ''
            ORDER BY CASE alias_type WHEN 'repo_path' THEN 0 ELSE 1 END, confidence DESC, id DESC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if alias_row is None:
            return None
        return str(alias_row["alias_value"])

    def _git_has_uncommitted_changes(self, cwd: Path) -> bool:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False
        return bool((result.stdout or "").strip())

    def _git_value(self, cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return (result.stdout or "").strip()

    def _parse_evidence(self, raw: str) -> dict:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _refresh_project_deployments(self, conn, project_id: int, repo_path: Path) -> None:
        targets = self._detect_deploy_targets(str(repo_path))
        existing_rows = conn.execute(
            """
            SELECT provider, environment
            FROM deploy_snapshots
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchall()
        existing_keys = {(str(row["provider"]), str(row["environment"])) for row in existing_rows}
        target_keys = {(str(item["provider"]), str(item["environment"])) for item in targets}

        for target in targets:
            provider = str(target["provider"])
            environment = str(target["environment"])
            if (provider, environment) in existing_keys:
                conn.execute(
                    """
                    UPDATE deploy_snapshots
                    SET state = CASE
                        WHEN state IN ('available', 'manual') THEN ?
                        ELSE state
                    END,
                    updated_at = ?
                    WHERE project_id = ? AND provider = ? AND environment = ?
                    """,
                    (
                        "available" if target.get("runnable") else "manual",
                        utc_now_iso(),
                        project_id,
                        provider,
                        environment,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO deploy_snapshots (project_id, provider, environment, state, updated_at, url)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        provider,
                        environment,
                        "available" if target.get("runnable") else "manual",
                        utc_now_iso(),
                        None,
                    ),
                )

        for provider, environment in existing_keys.difference(target_keys):
            conn.execute(
                """
                DELETE FROM deploy_snapshots
                WHERE project_id = ? AND provider = ? AND environment = ?
                """,
                (project_id, provider, environment),
            )

    def _detect_deploy_targets(self, local_path: str | None) -> list[dict]:
        if not local_path:
            return []
        repo_path = Path(local_path)
        if not repo_path.exists():
            return []

        targets: list[dict] = []
        for spec in DEPLOY_TARGET_SPECS:
            matched_marker = next((marker for marker in spec["markers"] if (repo_path / marker).exists()), None)
            if matched_marker is None:
                continue
            command = str(spec["command"])
            executable = command.split(" ", 1)[0] if command else ""
            targets.append(
                {
                    "provider": spec["provider"],
                    "environment": spec["environment"],
                    "marker": matched_marker,
                    "command": command,
                    "runnable": bool(executable and shutil.which(executable)),
                    "state": "available" if executable and shutil.which(executable) else "manual",
                }
            )
        return targets

    def _merge_deployments(self, *, saved_rows: list[dict], detected_targets: list[dict]) -> list[dict]:
        detected_by_key = {
            (str(item["provider"]), str(item["environment"])): item
            for item in detected_targets
        }
        merged: list[dict] = []
        for saved in saved_rows:
            key = (str(saved["provider"]), str(saved["environment"]))
            detected = detected_by_key.pop(key, None)
            merged.append(
                {
                    "provider": saved["provider"],
                    "environment": saved["environment"],
                    "state": saved["state"] if saved.get("state") not in {"available", "manual"} else (
                        detected["state"] if detected else saved["state"]
                    ),
                    "updated_at": saved.get("updated_at"),
                    "url": saved.get("url"),
                    "marker": detected.get("marker") if detected else "",
                    "command": detected.get("command") if detected else "",
                    "runnable": bool(detected and detected.get("runnable")),
                }
            )
        for detected in detected_by_key.values():
            merged.append(
                {
                    "provider": detected["provider"],
                    "environment": detected["environment"],
                    "state": detected["state"],
                    "updated_at": None,
                    "url": None,
                    "marker": detected["marker"],
                    "command": detected["command"],
                    "runnable": detected["runnable"],
                }
            )
        return sorted(merged, key=lambda item: (str(item["provider"]), str(item["environment"])))

    def _sync_agent_activity(self, *, source: str, sessions_root: Path, glob_pattern: str) -> dict:
        if not sessions_root.exists():
            self._mark_sync_state(source, success=False, error_summary=f"Missing sessions root: {sessions_root}")
            return {"status": "skipped", "reason": f"Missing sessions root: {sessions_root}", "inserted": 0}

        inserted = 0
        files = sorted(sessions_root.rglob(glob_pattern), key=lambda path: path.stat().st_mtime, reverse=True)[:300]
        with self.db.connect() as conn:
            projects = conn.execute(
                """
                SELECT id, display_name, primary_local_path
                FROM projects
                ORDER BY id
                """
            ).fetchall()
            aliases = conn.execute(
                """
                SELECT project_id, alias_type, alias_value
                FROM project_aliases
                WHERE alias_type IN ('repo_path', 'cwd')
                """
            ).fetchall()
            project_map = self._build_project_path_map(projects, aliases)
            for session_file in files:
                session_data = self._read_first_json_line(session_file)
                if not session_data:
                    continue
                cwd = self._extract_session_cwd(source, session_data)
                if not cwd:
                    continue
                repo_path = self._find_git_root(Path(cwd))
                matched_project_id = self._match_project_id(project_map, repo_path or Path(cwd))
                if matched_project_id is None:
                    continue

                raw_ref = str(session_file)
                exists = conn.execute(
                    """
                    SELECT 1
                    FROM agent_events
                    WHERE project_id = ? AND source = ? AND raw_ref = ?
                    """,
                    (matched_project_id, source, raw_ref),
                ).fetchone()
                if exists is not None:
                    continue

                occurred_at = datetime.fromtimestamp(session_file.stat().st_mtime, tz=timezone.utc).isoformat()
                session_id = self._extract_session_id(source, session_data)
                summary = f"{source} session seen in {repo_path or cwd}"
                conn.execute(
                    """
                    INSERT INTO agent_events
                    (project_id, source, event_type, occurred_at, session_id, summary, raw_ref)
                    VALUES (?, ?, 'session_seen', ?, ?, ?, ?)
                    """,
                    (matched_project_id, source, occurred_at, session_id, summary, raw_ref),
                )
                inserted += 1
            conn.commit()
        self._mark_sync_state(source, success=True, error_summary=None)
        return {"status": "completed", "inserted": inserted}

    def _recent_runs_for_project(self, project_id: int, *, limit: int) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, agent_type, skill_name, status, started_at, finished_at, output_summary
                FROM agent_runs
                WHERE project_id = ?
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                (project_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def _derive_attention(self, project: dict, recent_runs: list[dict]) -> list[dict]:
        attention = []
        repo_snapshot = project.get("repo_snapshot")
        repo_synced_at = project.get("repo_synced_at")
        has_uncommitted_changes = project.get("has_uncommitted_changes")
        pr_state = str(project.get("pr_state") or "unknown")
        checks_state = str(project.get("checks_state") or "unknown")

        if repo_snapshot is None and not repo_synced_at:
            attention.append(
                {
                    "severity": "high",
                    "type": "missing_repo_snapshot",
                    "title": "Repo snapshot missing",
                    "detail": "Project has no repo snapshot yet.",
                }
            )
        else:
            snapshot_time = self._parse_iso_datetime(
                str((repo_snapshot or {}).get("synced_at") or repo_synced_at or "")
            )
            if snapshot_time is not None and snapshot_time < datetime.now(timezone.utc) - timedelta(hours=STALE_REPO_HOURS):
                attention.append(
                    {
                        "severity": "medium",
                        "type": "stale_repo_snapshot",
                        "title": "Repo snapshot is stale",
                        "detail": f"Last repo sync was at {snapshot_time.isoformat()}",
                    }
                )

        if bool((repo_snapshot or {}).get("has_uncommitted_changes", has_uncommitted_changes)):
            attention.append(
                {
                    "severity": "medium",
                    "type": "dirty_worktree",
                    "title": "Uncommitted local changes",
                    "detail": "Project worktree is dirty.",
                }
            )

        if checks_state in {"failure", "failed", "error"}:
            attention.append(
                {
                    "severity": "high",
                    "type": "checks_failed",
                    "title": "PR checks are failing",
                    "detail": f"Latest check state is {checks_state}.",
                }
            )
        elif pr_state == "open" and checks_state in {"pending", "unknown"}:
            attention.append(
                {
                    "severity": "low",
                    "type": "checks_pending",
                    "title": "PR checks need review",
                    "detail": f"Open PR has check state {checks_state}.",
                }
            )

        for run in recent_runs[:3]:
            status = str(run.get("status") or "")
            summary = str(run.get("output_summary") or "")
            if status == "failed":
                severity = "high" if "not found on PATH" in summary else "medium"
                issue_type = "missing_agent_binary" if "not found on PATH" in summary else "run_failed"
                title = "Agent binary missing" if issue_type == "missing_agent_binary" else "Recent agent run failed"
                attention.append(
                    {
                        "severity": severity,
                        "type": issue_type,
                        "title": title,
                        "detail": summary or "A recent run failed.",
                    }
                )
                break
            if status == "cancelling":
                attention.append(
                    {
                        "severity": "low",
                        "type": "run_cancelling",
                        "title": "Run is cancelling",
                        "detail": summary or "A run is waiting to terminate.",
                    }
                )
                break
            if status == "running":
                attention.append(
                    {
                        "severity": "low",
                        "type": "run_active",
                        "title": "Run in progress",
                        "detail": summary or "An agent run is currently active.",
                    }
                )
                break

        return sorted(attention, key=self._attention_sort_key)

    def _highest_attention_severity(self, attention: list[dict]) -> str:
        if not attention:
            return "none"
        return attention[0]["severity"]

    def _attention_sort_key(self, issue: dict) -> tuple[int, str]:
        priority = {"high": 0, "medium": 1, "low": 2}.get(str(issue.get("severity")), 3)
        return (priority, str(issue.get("title") or ""))

    def _parse_iso_datetime(self, raw: str) -> datetime | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def _build_project_path_map(self, projects, aliases) -> dict[str, int]:
        project_map: dict[str, int] = {}
        for project in projects:
            local_path = str(project["primary_local_path"] or "").strip()
            if local_path:
                project_map[str(Path(local_path).resolve())] = int(project["id"])
        for alias in aliases:
            alias_value = str(alias["alias_value"] or "").strip()
            if alias_value:
                project_map[str(Path(alias_value).resolve())] = int(alias["project_id"])
        return project_map

    def _match_project_id(self, project_map: dict[str, int], path: Path) -> int | None:
        current = path.resolve()
        while True:
            matched = project_map.get(str(current))
            if matched is not None:
                return matched
            if current.parent == current:
                return None
            current = current.parent

    def _extract_session_cwd(self, source: str, session_data: dict) -> str:
        if source == "codex":
            payload = session_data.get("payload") or {}
            return str(payload.get("cwd") or "").strip()
        return str(session_data.get("cwd") or "").strip()

    def _extract_session_id(self, source: str, session_data: dict) -> str | None:
        if source == "codex":
            payload = session_data.get("payload") or {}
            value = payload.get("id")
            return str(value) if value else None
        value = session_data.get("id")
        return str(value) if value else None

    def _sync_project_github(self, project_id: int) -> str:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT id, remote_url
                FROM projects
                WHERE id = ?
                """,
                (project_id,),
            ).fetchone()
            if row is None:
                return "error"

            owner_repo = self._parse_github_owner_repo(str(row["remote_url"] or ""))
            if owner_repo is None:
                return "skipped"

            owner, repo = owner_repo
            try:
                pulls = self._github_json(f"/repos/{owner}/{repo}/pulls?state=open&per_page=1")
            except Exception as exc:
                self._mark_sync_state("github", success=False, error_summary=str(exc))
                return "error"

            if not pulls:
                conn.execute(
                    """
                    INSERT INTO pull_request_snapshots (project_id, provider, state, checks_state, updated_at, url)
                    VALUES (?, 'github', 'none', 'unknown', ?, NULL)
                    ON CONFLICT(project_id) DO UPDATE SET
                        provider = excluded.provider,
                        state = excluded.state,
                        checks_state = excluded.checks_state,
                        updated_at = excluded.updated_at,
                        url = excluded.url
                    """,
                    (project_id, utc_now_iso()),
                )
                conn.commit()
                return "synced"

            pull = pulls[0]
            head_sha = str(((pull.get("head") or {}).get("sha")) or "")
            checks_state = "unknown"
            if head_sha:
                status_json = self._github_json(f"/repos/{owner}/{repo}/commits/{head_sha}/status")
                checks_state = str(status_json.get("state") or "unknown")

            conn.execute(
                """
                INSERT INTO pull_request_snapshots (project_id, provider, state, checks_state, updated_at, url)
                VALUES (?, 'github', ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    provider = excluded.provider,
                    state = excluded.state,
                    checks_state = excluded.checks_state,
                    updated_at = excluded.updated_at,
                    url = excluded.url
                """,
                (
                    project_id,
                    str(pull.get("state") or "open"),
                    checks_state,
                    utc_now_iso(),
                    str(pull.get("html_url") or ""),
                ),
            )
            conn.commit()
        return "synced"

    def _parse_github_owner_repo(self, remote_url: str) -> tuple[str, str] | None:
        value = remote_url.strip()
        if not value:
            return None
        if value.startswith("git@github.com:"):
            path = value.split("git@github.com:", 1)[1]
        elif "github.com/" in value:
            parsed = urllib.parse.urlparse(value)
            path = parsed.path.lstrip("/")
        else:
            return None
        if path.endswith(".git"):
            path = path[:-4]
        parts = [part for part in path.split("/") if part]
        if len(parts) < 2:
            return None
        return (parts[0], parts[1])

    def _github_json(self, path: str) -> dict | list:
        request = urllib.request.Request(
            f"https://api.github.com{path}",
            headers=self._github_headers(),
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"GitHub API error {exc.code}: {body[:200]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GitHub API request failed: {exc.reason}") from exc

    def _github_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "project-radar",
        }
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"
        return headers

    def _read_first_json_line(self, path: Path) -> dict | None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                line = handle.readline().strip()
        except OSError:
            return None
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    def _mark_sync_state(self, source: str, *, success: bool, error_summary: str | None) -> None:
        with self.db.connect() as conn:
            if success:
                conn.execute(
                    """
                    UPDATE sync_state
                    SET last_success_at = ?, last_error_at = NULL, last_error_summary = NULL
                    WHERE source = ?
                    """,
                    (utc_now_iso(), source),
                )
            else:
                conn.execute(
                    """
                    UPDATE sync_state
                    SET last_error_at = ?, last_error_summary = ?
                    WHERE source = ?
                    """,
                    (utc_now_iso(), (error_summary or "")[:500], source),
                )
            conn.commit()

    def _mark_deploy_state(self, project_id: int, *, provider: str, state: str) -> None:
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE deploy_snapshots
                SET state = ?, updated_at = ?
                WHERE project_id = ? AND provider = ?
                """,
                (state, utc_now_iso(), project_id, provider),
            )
            if cursor.rowcount == 0:
                conn.execute(
                    """
                    INSERT INTO deploy_snapshots (project_id, provider, environment, state, updated_at, url)
                    VALUES (?, ?, 'production', ?, ?, NULL)
                    """,
                    (project_id, provider, state, utc_now_iso()),
                )
            conn.commit()

    def _load_deployments_for_project(self, project_id: int) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT provider, environment, state, updated_at, url
                FROM deploy_snapshots
                WHERE project_id = ?
                ORDER BY provider ASC, environment ASC, updated_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]
