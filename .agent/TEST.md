# Local verification (headless CI / Docker)

Run these commands sequentially from the repository root.

```bash
set -euxo pipefail
export CI=true

# 1. Backend Setup: Only create the venv if missing
if [ ! -f ".venv/bin/activate" ]; then
    rm -rf .venv
    python3 -m venv .venv
fi

# ALWAYS activate and install requirements to catch missing dependencies
. .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r backend/requirements.txt

# 2. Frontend Setup
if [ ! -d "frontend/node_modules" ]; then
    npm --prefix frontend install --no-audit --prefer-offline
fi

# 3. Backend Verification & Tests
python -m compileall -q backend
python -m pytest backend/tests -v

# 4. API Client Generation
# uvicorn runs from repo root; backend/main.py imports top-level
# "core"/"hardware"/"routers"/"services" packages, so the backend
# directory must be on PYTHONPATH for those imports to resolve.
export PYTHONPATH=backend
python -m uvicorn backend.main:app --port 8000 &
BACKEND_PID=$!
timeout 15 bash -c 'until curl -s http://127.0.0.1:8000/openapi.json > /dev/null; do sleep 1; done'
npm --prefix frontend run generate-api
kill $BACKEND_PID
unset PYTHONPATH

# 5. Frontend Verification & Tests
npm --prefix frontend run build
node --test "frontend/tests/**/*.js"
```
