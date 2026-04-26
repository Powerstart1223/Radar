"""FastAPI routes for Project Radar."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.core.config import Settings
from app.services.discovery import DiscoveryService
from app.services.projects import ProjectService
from app.services.runs import RunService
from app.services.system import SystemService


def build_router(
    *,
    settings: Settings,
    discovery: DiscoveryService,
    projects: ProjectService,
    runs: RunService,
    system: SystemService,
) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict:
        return {"ok": True, "app": settings.app_name}

    @router.get("/api/status")
    def get_status() -> dict:
        return system.status()

    @router.get("/api/projects")
    def list_projects() -> dict:
        return {"items": projects.list_projects()}

    @router.get("/api/attention")
    def list_attention() -> dict:
        return {"items": projects.list_attention_queue()}

    @router.get("/api/activity")
    def list_activity(limit: int = Query(default=20, ge=1, le=100)) -> dict:
        return {"items": projects.list_recent_activity(limit=limit)}

    @router.get("/api/projects/{project_id}")
    def get_project(project_id: int) -> dict:
        project = projects.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    @router.post("/api/projects/refresh")
    def refresh_all_projects() -> dict:
        return projects.refresh_all_project_repos()

    @router.post("/api/projects/{project_id}/refresh")
    def refresh_project(project_id: int) -> dict:
        try:
            return projects.refresh_project_repo(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/projects/{project_id}/sync/github")
    def sync_project_github(project_id: int) -> dict:
        return projects.sync_github_pull_requests(project_id)

    @router.post("/api/projects/{project_id}/deploy")
    def deploy_project(project_id: int) -> dict:
        try:
            payload = projects.prepare_deploy_run(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        run_id = runs.queue_run(payload)
        return {"run_id": run_id, "status": "queued", "provider": payload["skill_name"].split(":", 1)[1]}

    @router.get("/api/discovery/candidates")
    def list_candidates() -> dict:
        return {"items": discovery.list_candidates()}

    @router.post("/api/discovery/run")
    def run_discovery(payload: dict | None = None) -> dict:
        roots = []
        if payload and isinstance(payload.get("roots"), list):
            roots = [str(item) for item in payload["roots"]]
        if not roots:
            roots = [str(Path.home())]
        return discovery.run_discovery(roots)

    @router.post("/api/sync/codex")
    def sync_codex() -> dict:
        return projects.sync_codex_activity()

    @router.post("/api/sync/openclaw")
    def sync_openclaw() -> dict:
        return projects.sync_openclaw_activity()

    @router.post("/api/sync/github")
    def sync_github() -> dict:
        return projects.sync_github_pull_requests()

    @router.post("/api/discovery/confirm")
    def confirm_candidate(payload: dict) -> dict:
        candidate_id = payload.get("candidate_id")
        owner = payload.get("owner", "local")
        if not candidate_id:
            raise HTTPException(status_code=400, detail="candidate_id is required")
        try:
            return projects.confirm_candidate(int(candidate_id), owner=str(owner))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/discovery/merge")
    def merge_candidate(payload: dict) -> dict:
        candidate_id = payload.get("candidate_id")
        project_id = payload.get("project_id")
        if not candidate_id or not project_id:
            raise HTTPException(status_code=400, detail="candidate_id and project_id are required")
        try:
            return projects.merge_candidate(int(candidate_id), int(project_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/runs")
    def list_runs(project_id: int | None = Query(default=None)) -> dict:
        return {"items": runs.list_runs(project_id)}

    @router.get("/api/skills")
    def list_skills() -> dict:
        return {"items": runs.list_skills()}

    @router.post("/api/runs")
    def create_run(payload: dict) -> dict:
        required = {"project_id", "agent_type", "skill_name", "cwd"}
        missing = sorted(required.difference(payload))
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing fields: {', '.join(missing)}")
        run_id = runs.queue_run(payload)
        return {"run_id": run_id, "status": "queued"}

    @router.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: int) -> dict:
        try:
            return runs.cancel_run(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/runs/{run_id}/log")
    def get_run_log(run_id: int, max_bytes: int = Query(default=24000, ge=1000, le=200000)) -> dict:
        try:
            return runs.get_run_log(run_id, max_bytes=max_bytes)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
