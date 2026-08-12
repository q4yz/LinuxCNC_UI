#!/bin/bash
# shellcheck shell=bash
# Run the lifespan SIGILL diagnostic.
#
# Usage: bash scripts/run_diag_lifespan.sh
#
# Activates the backend venv, then runs
# ``backend/scripts/diag_lifespan_steps.py`` with a 30s timeout.
# Captures exit code:
#   * 0     - all probes passed
#   * 1     - one or more Python-level failures
#   * 132   - SIGILL (128 + 4); the last line on stdout is the
#             probe that triggered the SIGILL

set -e

# Resolve the repo root regardless of where the script is invoked from.
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT/backend"

if [ ! -d venv ]; then
    echo "Error: venv/ not found at backend/venv" >&2
    exit 1
fi

# shellcheck disable=SC1091
source venv/bin/activate

# Force unbuffered Python output so the last printed line is what
# we last executed before SIGILL aborted the process.
export PYTHONUNBUFFERED=1

echo "running backend/scripts/diag_lifespan_steps.py with 30s timeout..."
echo

# `timeout` from coreutils sends SIGTERM at 30s; SIGILL from the
# script will trip the timeout into reporting the kill code (132).
timeout 30 python scripts/diag_lifespan_steps.py
EC=$?

echo
echo "exit code: $EC"
case "$EC" in
    0)   echo "result: all probes passed" ;;
    1)   echo "result: one or more Python-level failures (see FAILED lines above)" ;;
    124) echo "result: timed out after 30s" ;;
    132) echo "result: SIGILL (signal 4) — last line printed before the crash is the culprit probe" ;;
    *)  echo "result: unexpected exit code" ;;
esac

exit $EC
