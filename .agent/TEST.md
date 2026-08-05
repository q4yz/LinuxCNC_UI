# Local verification (headless CI / Docker)

Run these commands sequentially from the repository root. The script is executed entirely autonomously inside a headless Docker container by the orchestrator. Every command is synchronous, non-interactive, and exits on its own — nothing here starts a dev server, opens a browser, or expects a display. The project has no formal automated test suite, so Python byte-compilation and the production frontend build are the required checks. The install steps are guarded with idempotent conditionals so repeat runs only re-run the checks when the cache is cold.

````bash
set -euxo pipefail

# ============================================================================ #
# Setup: ensure Python virtualenv and frontend dependencies are installed once. #
# ============================================================================ #

# --- Headless container flags ---------------------------------------------- #
# Export CI=true so Node and Python tools know they are running non-interactively
# in a headless CI environment. Node disables progress bars and interactive
# prompts; pip/npm keep their output machine-friendly. Without this, an
# interactive prompt can wedge the Docker process forever.
export CI=true

# --- Backend: create the virtualenv on first run, then install deps. --- #
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  # shellcheck disable=SC1091
  . .venv/bin/activate
  python -m pip install -q --no-input --disable-pip-version-check --upgrade pip
  python -m pip install -q --no-input --disable-pip-version-check -r backend/requirements.txt
else
  # shellcheck disable=SC1091
  . .venv/bin/activate
fi

# --- Frontend: install npm deps only when node_modules is missing. --- #
# --no-audit skips npm's network audit (slow + irrelevant in CI).
# --prefer-offline reuses the local npm cache so the install never hangs on
# a flaky registry response inside the container.
if [ ! -d "frontend/node_modules" ]; then
  npm --prefix frontend ci --no-audit --prefer-offline
fi

# ============================================================================ #
# Verification: run the project-wide build checks.                            #
# ============================================================================ #
# This phase is intentionally synchronous. Do NOT add commands that start a
# long-running dev server (`npm run dev`, `npm start`, `python main.py`),
# open a browser, or expect a display server. Each check must exit cleanly
# on its own and never leave a background process behind.

# Python syntax check.
python -m compileall -q backend

# Frontend production build (Vite is non-interactive and CI-safe by default).
npm --prefix frontend run build
````
