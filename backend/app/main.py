"""FastAPI application entrypoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import build_router
from app.core.config import get_settings
from app.db.database import Database
from app.services.discovery import DiscoveryService
from app.services.projects import ProjectService
from app.services.runs import RunService
from app.services.system import SystemService

settings = get_settings()
db = Database(settings.db_path)
db.init()

discovery = DiscoveryService(db, settings)
projects = ProjectService(db, settings)
runs = RunService(db, base_dir=settings.base_dir)
system = SystemService(db, projects)

app = FastAPI(title=settings.app_name)
app.include_router(
    build_router(
        settings=settings,
        discovery=discovery,
        projects=projects,
        runs=runs,
        system=system,
    )
)

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.on_event("startup")
def startup() -> None:
    projects.start_background_release_sync()
    runs.start()


@app.on_event("shutdown")
def shutdown() -> None:
    runs.stop()
    projects.stop_background_release_sync()
