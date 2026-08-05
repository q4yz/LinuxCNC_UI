# Local verification

Run these commands sequentially from the repository root. The project has no formal automated test suite, so Python byte-compilation and the production frontend build are the required checks. The install steps are guarded with idempotent conditionals so repeat runs only re-run the checks.

````bash
set -e

# Bootstrap the Python virtualenv only when it is missing.
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -r backend/requirements.txt
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Install frontend dependencies only when node_modules is missing.
if [ ! -d "frontend/node_modules" ]; then
  npm --prefix frontend ci
fi

# Required checks.
python -m compileall -q backend
npm --prefix frontend run build
````
