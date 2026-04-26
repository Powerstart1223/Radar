# Project Radar

Standalone local operator portal for Codex and OpenClaw projects.

## Current scaffold

This current build includes:

- FastAPI backend
- SQLite schema bootstrap
- real discovery from git repos plus Codex/OpenClaw session stores
- project review, repo refresh, GitHub sync, and attention queues
- agent run queueing with logs per project
- deployment target detection for common providers, provider console links, and one-click deploy when a local provider CLI is available
- live deployment status enrichment for Vercel, Netlify, and Render when `PROJECT_RADAR_VERCEL_TOKEN`, `PROJECT_RADAR_NETLIFY_TOKEN`, or `PROJECT_RADAR_RENDER_TOKEN` are set
- portfolio operations board for runs and deployments across all projects
- local HTML shell at `/`

## Run locally

```powershell
cd C:\Users\SJK\Documents\project-radar\backend
python -m pip install -r requirements.txt
python main.py
```

Then open:

```text
http://127.0.0.1:8787
```

## Next build steps

1. Persist provider-specific deployment URLs and last-known release metadata from live APIs where credentials are available.
2. Expand deployment adapters beyond the current file-marker providers.
3. Add richer deploy history and release drill-downs across the portfolio.
