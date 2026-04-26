"""Discovery services for candidate project collection."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from app.core.config import Settings
from app.db.database import Database, utc_now_iso

SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "AppData",
    ".cache",
    ".codex",
    ".openclaw",
}


class DiscoveryService:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    def run_discovery(self, roots: list[str]) -> dict:
        candidates = self._collect_candidates(roots)
        inserted = self._insert_candidates(candidates)
        self._mark_discovery_success()
        return {
            "queued_candidates": inserted,
            "by_source": self._count_by_source(candidates),
            "roots": roots,
        }

    def list_candidates(self) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, candidate_type, display_name, source, evidence_json, confidence, review_status, created_at
                FROM discovery_candidates
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def _collect_candidates(self, roots: list[str]) -> list[tuple[str, str, str, str, float, str]]:
        candidates: list[tuple[str, str, str, str, float, str]] = []
        seen_keys: set[tuple[str, str, str]] = set()

        for root in roots:
            for candidate in self._discover_git_repos(Path(root)):
                key = (candidate[0], candidate[1], candidate[3])
                if key not in seen_keys:
                    seen_keys.add(key)
                    candidates.append(candidate)

        for candidate in self._discover_codex_sessions():
            key = (candidate[0], candidate[1], candidate[3])
            if key not in seen_keys:
                seen_keys.add(key)
                candidates.append(candidate)

        for candidate in self._discover_openclaw_sessions():
            key = (candidate[0], candidate[1], candidate[3])
            if key not in seen_keys:
                seen_keys.add(key)
                candidates.append(candidate)

        return candidates

    def _discover_git_repos(self, root: Path) -> list[tuple[str, str, str, str, float, str]]:
        if not root.exists() or not root.is_dir():
            return []

        candidates: list[tuple[str, str, str, str, float, str]] = []
        for current_root, dirs, _files in os.walk(root):
            current_path = Path(current_root)
            dirs[:] = [name for name in dirs if name not in SKIP_DIR_NAMES]
            if (current_path / ".git").exists():
                remote_url = self._git_value(current_path, "remote", "get-url", "origin")
                default_branch = self._git_value(current_path, "symbolic-ref", "--short", "HEAD")
                evidence = {
                    "repo_path": str(current_path),
                    "remote_url": remote_url,
                    "default_branch": default_branch,
                }
                candidates.append(
                    (
                        "git_repo",
                        current_path.name,
                        "git_scan",
                        json.dumps(evidence, sort_keys=True),
                        0.95,
                        utc_now_iso(),
                    )
                )
                dirs[:] = []
        return candidates

    def _discover_codex_sessions(self, limit: int = 300) -> list[tuple[str, str, str, str, float, str]]:
        root = self.settings.codex_sessions_root
        if not root.exists():
            return []

        candidates: list[tuple[str, str, str, str, float, str]] = []
        files = sorted(root.rglob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)[:limit]
        for session_file in files:
            first_record = self._read_first_json_line(session_file)
            if not first_record or first_record.get("type") != "session_meta":
                continue
            payload = first_record.get("payload") or {}
            cwd = str(payload.get("cwd") or "").strip()
            if not cwd:
                continue
            repo_root = self._find_git_root(Path(cwd))
            display_name = repo_root.name if repo_root else Path(cwd).name or cwd
            evidence = {
                "cwd": cwd,
                "repo_path": str(repo_root) if repo_root else "",
                "session_file": str(session_file),
                "session_id": payload.get("id"),
            }
            confidence = 0.9 if repo_root else 0.45
            candidates.append(
                (
                    "codex_session",
                    display_name,
                    "codex_session",
                    json.dumps(evidence, sort_keys=True),
                    confidence,
                    utc_now_iso(),
                )
            )
        return candidates

    def _discover_openclaw_sessions(self, limit: int = 200) -> list[tuple[str, str, str, str, float, str]]:
        root = self.settings.openclaw_sessions_root
        if not root.exists():
            return []

        candidates: list[tuple[str, str, str, str, float, str]] = []
        files = sorted(root.glob("*.jsonl*"), key=lambda path: path.stat().st_mtime, reverse=True)[:limit]
        for session_file in files:
            first_record = self._read_first_json_line(session_file)
            if not first_record or first_record.get("type") != "session":
                continue
            cwd = str(first_record.get("cwd") or "").strip()
            if not cwd:
                continue
            repo_root = self._find_git_root(Path(cwd))
            display_name = repo_root.name if repo_root else Path(cwd).name or cwd
            evidence = {
                "cwd": cwd,
                "repo_path": str(repo_root) if repo_root else "",
                "session_file": str(session_file),
                "session_id": first_record.get("id"),
            }
            confidence = 0.85 if repo_root else 0.35
            candidates.append(
                (
                    "openclaw_session",
                    display_name,
                    "openclaw_session",
                    json.dumps(evidence, sort_keys=True),
                    confidence,
                    utc_now_iso(),
                )
            )
        return candidates

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

    def _find_git_root(self, path: Path) -> Path | None:
        current = path
        if current.is_file():
            current = current.parent
        while True:
            if (current / ".git").exists():
                return current
            if current.parent == current:
                return None
            current = current.parent

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

    def _insert_candidates(self, candidates: list[tuple[str, str, str, str, float, str]]) -> int:
        inserted = 0
        with self.db.connect() as conn:
            for candidate in candidates:
                existing = conn.execute(
                    """
                    SELECT id
                    FROM discovery_candidates
                    WHERE candidate_type = ? AND display_name = ? AND source = ? AND evidence_json = ?
                    """,
                    candidate[:4],
                ).fetchone()
                if existing is not None:
                    continue
                conn.execute(
                    """
                    INSERT INTO discovery_candidates
                    (candidate_type, display_name, source, evidence_json, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    candidate,
                )
                inserted += 1
            conn.commit()
        return inserted

    def _mark_discovery_success(self) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE sync_state
                SET last_success_at = ?, last_error_at = NULL, last_error_summary = NULL
                WHERE source = 'discovery'
                """,
                (utc_now_iso(),),
            )
            conn.commit()

    def _count_by_source(self, candidates: list[tuple[str, str, str, str, float, str]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for candidate in candidates:
            counts[candidate[2]] = counts.get(candidate[2], 0) + 1
        return counts
