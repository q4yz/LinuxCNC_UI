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

# GUARANTEE cleanup: Install a bash EXIT trap so the background uvicorn process
# is reaped on ANY exit path under `set -e` — whether the script completes
# successfully OR aborts mid-way because of a failed step (curl readiness probe
# timeout, generate-api failure, npm build failure, or node --test failure).
# Without this trap, an aborted run would leave uvicorn holding port 8000 and
# the next run would fail to start with a confusing "address already in use"
# error that can mislead an AI agent into diagnosing a non-existent networking
# bug in the application code. The trap is the sole terminator of the
# background uvicorn process — no explicit kill commands are needed later.
#
# Notes on the trap body:
#   * Single quotes are used so `$BACKEND_PID` is expanded at trap-FIRE time,
#     not trap-set time. This is a defensive pattern that does not rely on
#     `BACKEND_PID` being set before the trap is installed.
#   * `kill -- -"$BACKEND_PID"` targets the process group (negative PID),
#     which reaps any worker/child processes uvicorn may have spawned in
#     addition to the main process. A plain `kill "$BACKEND_PID"` would only
#     signal the parent, leaving children holding port 8000 as ghosts.
#   * The `wait` gives uvicorn a brief grace period to shut down before the
#     shell tears down stdio; the trailing `|| true` ensures the trap itself
#     never returns non-zero under `set -e`.
trap 'kill -- -"$BACKEND_PID" 2>/dev/null || true; wait "$BACKEND_PID" 2>/dev/null || true' EXIT

# Wait for the backend to become healthy (timeout after 15 seconds)
timeout 15 bash -c 'until curl -s http://127.0.0.1:8000/openapi.json > /dev/null; do sleep 1; done'

# Generate the API client schema
npm --prefix frontend run generate-api

# 5. Frontend Verification
npm --prefix frontend run build
node --test "frontend/tests/**/*.mjs"
```