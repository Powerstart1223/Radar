# Project Radar

Standalone local operator portal for Codex and OpenClaw projects.

## Current scaffold

This initial build includes:

- FastAPI backend
- SQLite schema bootstrap
- discovery candidate stub endpoint
- project and run API placeholders
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

1. Replace the discovery stub with real git/Codex/OpenClaw scanners.
2. Add canonical project merge/review flow.
3. Add isolated subprocess run launching per project.
