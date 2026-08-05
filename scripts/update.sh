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
# Using the standard venv path for this project
if [ -f "backend/venv/bin/pip" ]; then
    backend/venv/bin/pip install -r backend/requirements.txt
elif [ -f "backend/venv/Scripts/pip" ]; then
    backend/venv/Scripts/pip install -r backend/requirements.txt
else
    pip install -r backend/requirements.txt
fi

echo "Update Complete"