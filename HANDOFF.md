### Resolution Summary
`backend/routers/system.py` had a duplicated block that re-imported FastAPI, re-defined `APIRouter`, and re-defined `get_version` / `update_system`, causing the `/api/v1/system/version` and `/api/v1/system/update` routes to be declared twice (with the second set silently shadowing the first). I removed the duplicate block, kept the mock version handler as the source of truth (it matches the frontend `UpdateManager.vue` contract: `version`, `current_version`, `latest_version`, `update_available`), enriched it with the real `git rev-parse --short HEAD` value, and consolidated the imports and router initialization.

### Files Modified
- `backend/routers/system.py`: removed the second (lines 32-66) duplicate block; consolidated `logging` / `subprocess` / `os` imports into a single import block using `pathlib`; introduced a single `APIRouter(prefix="/api/v1/system", tags=["System"])`; unified the two `get_version` definitions into one that returns the git commit hash plus the existing mock version fields; kept the existing `/update` simulated-task implementation (it was already correct and is the one the frontend `api.triggerUpdate()` calls). No other files were touched.

### Architectural Decisions
- **Source of truth: mock + git hash.** The frontend `UpdateManager.vue` reads `res.version`, `res.current_version`, `res.latest_version`, and `res.update_available`. The mock payload provides all four fields, while the git-rev-parse version only returned `version`. To keep the frontend contract intact while still surfacing the real commit, the kept handler returns the git hash in the `version` field and preserves the rest of the mock payload. `git` failures degrade gracefully to `"unknown"` (with a `logger.warning`, not an exception), so the endpoint never raises.
- **Removed `os` in favor of `pathlib.Path`.** Matches the type-hinted / focused-function style encouraged by `.agent/AGENT.md` and removes a hand-rolled `os.path.dirname(...)` chain.
- **Kept the simulated background update.** The existing `time.sleep(5)` update task is the one the frontend wires up via `api.triggerUpdate()`; the `update.sh`-based alternative in the duplicate block was not referenced anywhere else in the repo and was not what the frontend expected. Switching to it would have been an unrelated behavior change beyond the scope of this issue.
- **No new endpoints, no prefix/tag changes.** `app.include_router(system.router)` in `backend/main.py` continues to work without modification.

### Testing Verification
- [x] Ran local test suite / build checks
- `python3 -m compileall -q backend` → exits 0, no diagnostics.
- Imported `from routers import system` and inspected routes: exactly one `GET /api/v1/system/version` and one `POST /api/v1/system/update` registered (previously 2 of each, with the second shadowing the first).
- Mounted the router in an isolated `FastAPI()` app and exercised both endpoints with `fastapi.testclient.TestClient`:
  - `GET /api/v1/system/version` → `200 {"version": "74bb770", "current_version": "v1.0.0", "latest_version": "v1.0.1", "update_available": True}` (commit hash is the real short hash of the current HEAD; falls back to `"unknown"` if git is unavailable).
  - `POST /api/v1/system/update` → `200 {"status": "update started"}`.
- `npm --prefix frontend run build` → production build succeeds (`vite build`, 894 modules transformed, `dist/` emitted).
- Note: `npm --prefix frontend ci` failed in this environment because the repo's `frontend/package-lock.json` is out of sync with `frontend/package.json` (a pre-existing repo state, not caused by this change). I used `npm --prefix frontend install` to populate `frontend/node_modules` so the build could run. The byte-compile + isolated `TestClient` exercise is sufficient to validate the fix.
- Note: a separate, pre-existing issue exists in `backend/routers/machine.py` — its `/upload` endpoint requires `python-multipart` to be installed. That is unrelated to issue #16 and out of scope here.
