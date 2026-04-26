"""SQLite schema bootstrap for Project Radar."""

from __future__ import annotations

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        display_name TEXT NOT NULL,
        primary_local_path TEXT,
        remote_url TEXT,
        default_branch TEXT,
        owner TEXT,
        status TEXT NOT NULL DEFAULT 'discovered',
        source_confidence REAL NOT NULL DEFAULT 0.0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS project_aliases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        alias_type TEXT NOT NULL,
        alias_value TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0.0,
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS discovery_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_type TEXT NOT NULL,
        display_name TEXT NOT NULL,
        source TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0.0,
        review_status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        source TEXT NOT NULL,
        event_type TEXT NOT NULL,
        occurred_at TEXT NOT NULL,
        session_id TEXT,
        summary TEXT,
        raw_ref TEXT,
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS repo_snapshots (
        project_id INTEGER PRIMARY KEY,
        branch TEXT,
        has_uncommitted_changes INTEGER NOT NULL DEFAULT 0,
        last_commit_at TEXT,
        remote_name TEXT,
        synced_at TEXT NOT NULL,
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pull_request_snapshots (
        project_id INTEGER PRIMARY KEY,
        provider TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'unknown',
        checks_state TEXT NOT NULL DEFAULT 'unknown',
        updated_at TEXT NOT NULL,
        url TEXT,
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deploy_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        provider TEXT NOT NULL,
        environment TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'unknown',
        updated_at TEXT NOT NULL,
        url TEXT,
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        severity TEXT NOT NULL,
        title TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        agent_type TEXT NOT NULL,
        skill_name TEXT NOT NULL,
        cwd TEXT NOT NULL,
        command TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        started_at TEXT NOT NULL,
        finished_at TEXT,
        output_summary TEXT,
        artifact_dir TEXT,
        log_path TEXT,
        FOREIGN KEY(project_id) REFERENCES projects(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS skill_definitions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        source TEXT NOT NULL,
        description TEXT NOT NULL,
        supports_codex INTEGER NOT NULL DEFAULT 1,
        supports_openclaw INTEGER NOT NULL DEFAULT 0,
        requires_interaction INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sync_state (
        source TEXT PRIMARY KEY,
        last_success_at TEXT,
        last_error_at TEXT,
        last_error_summary TEXT
    )
    """,
)
