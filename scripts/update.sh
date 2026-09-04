#!/bin/bash
# Make sure to run: chmod +x scripts/update.sh

# Exit immediately if a command exits with a non-zero status
set -e

echo "Starting update process..."
cd "$(dirname "$0")/.." || exit 1

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

echo "Pulling latest changes from git..."
git pull origin main

echo "Updating backend dependencies..."
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

echo "Restarting backend services..."
sudo systemctl restart linuxcnc-ui-machine linuxcnc-ui-system

echo "Update Complete"