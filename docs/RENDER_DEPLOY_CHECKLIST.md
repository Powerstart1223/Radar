# Render Deploy Checklist

Use this for the first hosted launch of Project Radar.

## 1. Create the service

- Create a new Render web service from `Powerstart1223/Radar`
- Use the repo root
- Let Render read [render.yaml](../render.yaml)

Expected service shape:

- Docker web service
- port `10000`
- health check path `/health`
- persistent disk mounted at `/var/data`

## 2. Set environment variables

Required:

- `PROJECT_RADAR_STORAGE_DIR=/var/data/project-radar`

Recommended:

- `PROJECT_RADAR_HOST=0.0.0.0`
- `PROJECT_RADAR_PORT=10000`

Optional live-provider features:

- `PROJECT_RADAR_GITHUB_TOKEN`
- `PROJECT_RADAR_VERCEL_TOKEN`
- `PROJECT_RADAR_NETLIFY_TOKEN`
- `PROJECT_RADAR_RENDER_TOKEN`

Optional local-session discovery overrides:

- `PROJECT_RADAR_CODEX_SESSIONS_ROOT`
- `PROJECT_RADAR_OPENCLAW_SESSIONS_ROOT`

Note:

- If the hosted environment does not have access to Codex/OpenClaw session roots, the app will still run, but local session-backed discovery and activity views will be reduced.

## 3. Deploy

- Trigger the first deploy
- Wait for the health check to pass on `/health`

Expected health response:

```json
{"ok": true, "app": "Project Radar"}
```

## 4. Verify the app

Check these paths manually after deploy:

- `/health`
- `/`
- `/api/status`
- `/api/projects`
- `/api/runs`
- `/api/deployments`
- `/api/releases`

## 5. Verify operator workflows

In the dashboard, confirm:

- the HTML shell loads
- the Operations Board renders
- the Session Restore panel does not error
- the Sync Banners section renders
- the Project list renders even if empty

If provider tokens are configured, also confirm:

- release rows show provider metadata
- deployment actions appear where supported
- `Sync Deployments` completes without breaking the board

## 6. Verify persistence

Check that persistent disk behavior is working:

- refresh the page and confirm restored UI state returns
- confirm `storage/`-backed data survives a restart
- confirm release snapshot cache still exists after restart

## 7. Common failure checks

If `/health` fails:

- confirm the service booted on `0.0.0.0:10000`
- confirm `fastapi` and `uvicorn` were installed by the Docker build
- inspect Render build logs for dependency install failures

If the app loads but portfolio data is thin:

- confirm session-root env vars are mounted or intentionally blank
- confirm provider tokens are set for live deployment enrichment
- confirm GitHub token is set if GitHub sync is expected

If deployment metadata is stale:

- use `Sync Deployments`
- check `/api/status` for `release_sync`
- inspect provider token configuration

## 8. First post-deploy actions

- run one manual `Sync Deployments`
- run one manual `Sync GitHub`
- open the `Releases` board
- verify the release cache banner and summary strip behave correctly
- verify `Clear Restored Session` resets dashboard UI state cleanly
