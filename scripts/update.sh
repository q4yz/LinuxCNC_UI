#!/bin/bash
# Make sure to run: chmod +x scripts/update.sh
#
# System update: git pull, dependencies, UI rebuild, service restart.
# Launched detached by the system service (POST /api/v1/system/update);
# can also be run by hand. Every step is recorded through
# scripts/update_status.py so the UI's update screen can follow it and
# only finishes on the final "done" (or shows "failed" with the log).

# Exit immediately if a command exits with a non-zero status
set -e

echo "Starting update process... ($(date -Is))"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

STATUS_SCRIPT="$PROJECT_DIR/scripts/update_status.py"
PHASE="starting"
DONE=0

status() {
    # status <state> <phase> [message] — never let a status write abort the update
    python3 "$STATUS_SCRIPT" "$@" || echo "Warning: could not write update status" >&2
}

phase() {
    PHASE="$1"
    echo "--- $1 ---"
    status running "$1"
}

on_exit() {
    local code=$?
    if [ "$DONE" -ne 1 ]; then
        echo "Update FAILED during '$PHASE' (exit code $code)" >&2
        status failed "$PHASE" "Update failed during '$PHASE' (exit code $code)"
    fi
}
trap on_exit EXIT

phase "checks"

# Safety Check 1: Ensure we are inside a valid git repository
if [ ! -d ".git" ]; then
    echo "Error: Not a valid git repository. Run this script from the project root." >&2
    exit 1
fi

# Safety Check 2: Check if LinuxCNC is currently running to prevent updating active system files
if pgrep -x "linuxcnc" > /dev/null || pgrep -x "emc" > /dev/null; then
    echo "Error: LinuxCNC is currently running. Please stop LinuxCNC before running the update." >&2
    exit 1
fi

phase "pull"
# Just 'git pull' so it updates whichever branch is currently checked out (e.g., dev or main)
git pull

phase "dependencies"
# One venv shared by both services (backend/machine + backend/system)
# — each service's own requirements file is installed into it. Falls
# back to the combined requirements.txt on an older checkout that
# predates the machine/system split.
if [ -f "backend/requirements-machine.txt" ] && [ -f "backend/requirements-system.txt" ]; then
    REQ_ARGS="-r backend/requirements-machine.txt -r backend/requirements-system.txt"
else
    REQ_ARGS="-r backend/requirements.txt"
fi

if [ -f "backend/venv/bin/pip" ]; then
    backend/venv/bin/pip install $REQ_ARGS
elif [ -f "backend/venv/Scripts/pip" ]; then
    backend/venv/Scripts/pip install $REQ_ARGS
else
    pip install $REQ_ARGS
fi

phase "stopping services"
# Only the system service (:8001) is a systemd unit — the machine
# backend (:8000) is spawned by the system service like a program,
# so there is no linuxcnc-ui-machine unit to stop here.
sudo /bin/systemctl stop linuxcnc-ui-system

echo "Cleaning up orphaned backend processes..."
pkill -f "uvicorn" || true
pkill -f "python.*backend" || true

phase "rebuilding UI"
# API client from the apps' schemas (no ports opened), frontend build,
# system service restart, nginx reload.
bash "$PROJECT_DIR/rebuild_ui.sh"

phase "waiting for services"
# "done" only once the restarted system service really answers — it is
# also the service that serves this status to the UI.
if ! timeout 120 bash -c 'until curl -sf http://127.0.0.1:8001/api/v1/system/version > /dev/null; do sleep 2; done'; then
    echo "Error: the system service did not come back within 120 s" >&2
    exit 1
fi

DONE=1
status done "finished" "Update complete"
echo "Update Complete! ($(date -Is))"
