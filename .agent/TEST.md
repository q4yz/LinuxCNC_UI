# Local verification

# .agent/TEST.md is invoked directly by ``/bin/sh`` (no shebang required)
# at orchestration time. Every line MUST therefore be either a blank
# line, a shell comment (starting with ``#``), or a runnable command.
# Markdown constructs (``##``, fenced code blocks starting with
# ```` ```bash ````) are NOT shell comments and would be interpreted
# as commands, so the prose below is fully commented out.
#
# Run these commands sequentially from the repository root. The
# project has no formal automated test suite, so Python byte
# compilation and the production frontend build are the required
# checks.

set -e
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
npm ci
npm --prefix frontend ci
python -m compileall -q backend
npm --prefix frontend run build
