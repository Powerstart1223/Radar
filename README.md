# Project Radar

Project Radar is a FastAPI control plane for monitoring and operating Codex and OpenClaw projects across a local portfolio.

It combines:

- local repo discovery and review queues
- project attention and sync health monitoring
- agent run queueing with per-project logs
- deployment target detection for common providers
- provider-enriched deployment state, history, rollback, and release feeds
- a stateful operator dashboard that restores the last working session

## Current capabilities

- discovery from local git repos plus Codex/OpenClaw session stores
- project review, repo refresh, GitHub sync, and attention queues
- global activity, runs, deployments, and releases views
- deployment detection for Vercel, Netlify, Fly.io, Railway, and Render
- direct provider actions:
  - Render deploy trigger
  - Netlify rollback
- live deployment metadata from Vercel, Netlify, and Render APIs when tokens are configured
- cached release snapshots with freshness, fallback, and health signals
- background deployment metadata refresh on startup
- session restore for board state, selected project lane, run logs, release details, deployment history expansion, and agent form drafts

## Local run

```powershell
cd C:\Users\SJK\Documents\project-radar\backend
python -m pip install -r requirements.txt
python main.py
```

Open `http://127.0.0.1:8787`.

Health check:

```text
http://127.0.0.1:8787/health
```

## Configuration

Copy `.env.example` and set only the values you need.

Core runtime:

- `PROJECT_RADAR_HOST`
- `PROJECT_RADAR_PORT`
- `PROJECT_RADAR_STORAGE_DIR`
- `PROJECT_RADAR_CODEX_SESSIONS_ROOT`
- `PROJECT_RADAR_OPENCLAW_SESSIONS_ROOT`

Optional provider/API tokens:

- `PROJECT_RADAR_GITHUB_TOKEN`
- `PROJECT_RADAR_VERCEL_TOKEN`
- `PROJECT_RADAR_NETLIFY_TOKEN`
- `PROJECT_RADAR_RENDER_TOKEN`

## Deployment

This repo is now prepared for container deployment.

Included artifacts:

- [Dockerfile](Dockerfile)
- [render.yaml](render.yaml)
- [backend/main.py](backend/main.py)
- [docs/RENDER_DEPLOY_CHECKLIST.md](docs/RENDER_DEPLOY_CHECKLIST.md)

### Render

The fastest path is Render using `render.yaml`.

What it configures:

- Docker web service
- `PROJECT_RADAR_HOST=0.0.0.0`
- `PROJECT_RADAR_PORT=10000`
- persistent disk mounted at `/var/data`
- health check at `/health`

Recommended environment variables for hosted use:

- `PROJECT_RADAR_STORAGE_DIR=/var/data/project-radar`
- provider tokens only if you want live provider enrichment/actions
- session-root overrides if the host has shared Codex/OpenClaw session paths available

## Deployment notes

- Hosted deployments without local Codex/OpenClaw session directories will still run, but local session-driven discovery/activity will be limited unless those roots are mounted or overridden.
- `storage/` is runtime state and is intentionally gitignored.
- Release and deployment feeds degrade to cached snapshots when provider APIs fail or go stale.

## Verification

Useful checks before ship:

```powershell
cd C:\Users\SJK\Documents\project-radar\backend
python -m py_compile app\main.py app\core\config.py app\services\projects.py tests\test_projects.py
python -m unittest tests.test_projects
```
