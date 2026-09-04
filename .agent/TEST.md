# Local verification (headless CI / Docker)

Run these commands sequentially from the repository root. The script is executed entirely autonomously inside a headless Docker container by the orchestrator. Every command is synchronous, non-interactive, and exits on its own — nothing here starts a dev server, opens a browser, or expects a display. The backend is split into three Python processes (`backend/common/` shared library, `backend/machine/` on :8000, `backend/system/` on :8001 — see [`.agent/context/ARCHITECTURE.md`](context/ARCHITECTURE.md)); their pytest suites must run as **separate** invocations (all three `tests/` directories share the bare name `tests` with no common package root, so collecting more than one in the same process raises `ImportPathMismatchError`). The install steps are guarded with idempotent conditionals so repeat runs only re-run the checks when the cache is cold.

> **Note on the venv cache check.** The script checks for the existence of the `activate` script itself (`[ ! -f ".venv/bin/activate" ]`), not just the `.venv` directory. Because `.venv/` is gitignored, an interrupted `python3 -m venv` can leave behind an empty folder that `git clean -fd` will not touch. A naïve `[ ! -d ".venv" ]` check would then skip the rebuild and fall through to a missing `activate` file. The hardened check rebuilds the venv from scratch whenever the activation file is missing, regardless of whether the parent folder exists.

```bash
set -euxo pipefail
export CI=true

# 1. Backend Setup — one venv shared by both apps (see install.sh).
# requirements-machine.txt / requirements-system.txt both currently
# just "-r requirements.txt" (the two apps have identical third-party
# deps today); installing both here exercises that they stay valid
# includes even if they diverge later.
if [ ! -f ".venv/bin/activate" ]; then
    rm -rf .venv
    python3 -m venv .venv --system-site-packages
    . .venv/bin/activate
    python -m pip install -q --upgrade pip
    python -m pip install -q -r backend/requirements-machine.txt -r backend/requirements-system.txt
else
    . .venv/bin/activate
fi

# 2. Frontend Setup
if [ ! -d "frontend/node_modules" ]; then
    npm --prefix frontend install --no-audit --prefer-offline
fi

# 3. Backend Verification — byte-compile everything, then run each
# app's pytest suite separately (see the note above).
python -m compileall -q backend
python -m pytest backend/common/tests -v
python -m pytest backend/machine/tests -v
python -m pytest backend/system/tests -v

# 4. API Client Generation — the typed client is generated from BOTH
# backends' merged OpenAPI schema (frontend/scripts/generate-api.mjs
# + merge-openapi.mjs), so both must be reachable. --app-dir points
# uvicorn at each app's own directory (equivalent to `cd` there) so
# each main.py's own sys.path bootstrap for backend/common resolves
# the same way it does in production.
python -m uvicorn main:app --app-dir backend/machine --port 8000 > /dev/null 2>&1 &
MACHINE_PID=$!
python -m uvicorn main:app --app-dir backend/system --port 8001 > /dev/null 2>&1 &
SYSTEM_PID=$!

# GUARANTEE cleanup: This tells bash to run the kill command the moment the script exits,
# whether it exits successfully or crashes due to an error.
trap "kill $MACHINE_PID $SYSTEM_PID 2>/dev/null || true" EXIT

# Wait for both backends to become healthy (timeout after 15 seconds each).
timeout 15 bash -c 'until curl -s http://127.0.0.1:8000/openapi.json > /dev/null; do sleep 1; done'
timeout 15 bash -c 'until curl -s http://127.0.0.1:8001/openapi.json > /dev/null; do sleep 1; done'

# Generate the API client schema
npm --prefix frontend run generate-api

# 5. Frontend Verification — production build + tests.
# (The old module-registry lints, check-no-lazy-imports.mjs and
# check-store-ids.mjs, were retired along with the dynamic frontend
# module registry they checked — there is no replacement lint step
# today; see the technical-debt list in .agent/HANDOFF.md § 2.)
npm --prefix frontend run build
node --test "frontend/tests/**/*.mjs"
```
