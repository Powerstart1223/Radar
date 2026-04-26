# Project Radar

Standalone local operator portal for Codex and OpenClaw projects.

## Current scaffold

This current build includes:

- FastAPI backend
- SQLite schema bootstrap
- real discovery from git repos plus Codex/OpenClaw session stores
- project review, repo refresh, GitHub sync, and attention queues
- agent run queueing with logs per project
- deployment target detection for common providers and one-click deploy when a local provider CLI is available
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

1. Add safer structured execution for queued runs instead of editable raw shell commands.
2. Expand deployment adapters beyond the current file-marker providers.
3. Add broader portfolio views for agent runs and deployment history.
