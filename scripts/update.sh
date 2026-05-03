#!/bin/bash
# Make sure to run: chmod +x scripts/update.sh

echo "Starting update process..."
cd "$(dirname "$0")/.." || exit 1

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
