# Local verification (headless CI / Docker)

Run these commands sequentially from the repository root. The script is executed entirely autonomously inside a headless Docker container by the orchestrator. Every command is synchronous, non-interactive, and exits on its own — nothing here starts a dev server, opens a browser, or expects a display. The project has no formal automated test suite, so Python byte-compilation and the production frontend build are the required checks. The install steps are guarded with idempotent conditionals so repeat runs only re-run the checks when the cache is cold.

> **Note on the venv cache check.** The script checks for the existence of the `activate` script itself (`[ ! -f ".venv/bin/activate" ]`), not just the `.venv` directory. Because `.venv/` is gitignored, an interrupted `python3 -m venv` can leave behind an empty folder that `git clean -fd` will not touch. A naïve `[ ! -d ".venv" ]` check would then skip the rebuild and fall through to a missing `activate` file. The hardened check rebuilds the venv from scratch whenever the activation file is missing, regardless of whether the parent folder exists.

```bash
set -euxo pipefail
export CI=true

# 1. Backend Setup
if [ ! -f ".venv/bin/activate" ]; then
    rm -rf .venv
    python3 -m venv .venv
    . .venv/bin/activate
    python -m pip install -q --upgrade pip
    python -m pip install -q -r backend/requirements.txt
else
    . .venv/bin/activate
fi

# 2. Frontend Setup
if [ ! -d "frontend/node_modules" ]; then
    npm --prefix frontend install --no-audit --prefer-offline
fi

# 3. Backend Verification
python -m compileall -q backend
python -m pytest backend/tests -v

# 4. API Client Generation
# Start the FastAPI backend in the background and detach its output so openapi.json is reachable.
python -m uvicorn backend.main:app --port 8000 > /dev/null 2>&1 &
BACKEND_PID=$!

# GUARANTEE cleanup: This tells bash to run the kill command the moment the script exits,
# whether it exits successfully or crashes due to an error.
trap "kill $BACKEND_PID 2>/dev/null || true" EXIT

# Wait for the backend to become healthy (timeout after 15 seconds)
timeout 15 bash -c 'until curl -s http://127.0.0.1:8000/openapi.json > /dev/null; do sleep 1; done'

# Generate the API client schema
npm --prefix frontend run generate-api

# 5. Frontend Verification
npm --prefix frontend run build
node --test "frontend/tests/**/*.mjs"
```
