# Local verification (headless CI / Docker)

Run these commands sequentially from the repository root. The script is executed entirely autonomously inside a headless Docker container by the orchestrator. Every command is synchronous, non-interactive, and exits on its own — nothing here starts a dev server, opens a browser, or expects a display. The project has no formal automated test suite, so Python byte-compilation and the production frontend build are the required checks. The install steps are guarded with idempotent conditionals so repeat runs only re-run the checks when the cache is cold.

> **Note on the venv cache check.** The script checks for the existence of the `activate` script itself (`[ ! -f ".venv/bin/activate" ]`), not just the `.venv` directory. Because `.venv/` is gitignored, an interrupted `python3 -m venv` can leave behind an empty folder that `git clean -fd` will not touch. A naïve `[ ! -d ".venv" ]` check would then skip the rebuild and fall through to a missing `activate` file. The hardened check rebuilds the venv from scratch whenever the activation file is missing, regardless of whether the parent folder exists.

````bash
set -euxo pipefail
export CI=true

# 1. Backend Setup
# Check for the activate file, not just the directory.
# If it's missing, nuke the folder to clear broken states and rebuild.
if [ ! -f ".venv/bin/activate" ]; then
    rm -rf .venv
    python3 -m venv .venv
    . .venv/bin/activate
    python -m pip install -q --upgrade pip
    python -m pip install -q -r backend/requirements.txt
else
    # Always activate, even if already installed
    . .venv/bin/activate
fi

# 2. Frontend Setup
if [ ! -d "frontend/node_modules" ]; then
    npm --prefix frontend ci --no-audit --prefer-offline
fi

# 3. Verification
python -m compileall -q backend
npm --prefix frontend run build
````
