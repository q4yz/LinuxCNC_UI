# Local verification

## Run these commands sequentially from the repository root. The project has no formal automated test suite, so Python byte-compilation and the production frontend build are the required checks.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
npm ci
npm --prefix frontend ci
python -m compileall -q backend
npm --prefix frontend run build
```