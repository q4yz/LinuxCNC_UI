#!/bin/bash

# Give Axis and the HAL 2 seconds to fully boot up before we connect
sleep 2

# Safety Check 1: Ensure the project directory exists
PROJECT_DIR="/home/linuxcnc/Downloads/LinuxCNC_UI"
if [ ! -d "$PROJECT_DIR" ]; then
    echo "Error: Project directory $PROJECT_DIR does not exist." >&2
    exit 1
fi

# Go to your project directory
cd "$PROJECT_DIR/backend" || exit 1

# Safety Check 2: Ensure the backend virtual environment exists
if [ ! -f "venv/bin/activate" ]; then
    echo "Error: Backend virtual environment not found at backend/venv." >&2
    exit 1
fi

# 1. Start the FastAPI backend in the background.
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

cd "$PROJECT_DIR/frontend" || { kill $BACKEND_PID 2>/dev/null; exit 1; }

# Safety Check 3: Ensure node_modules exists for the frontend
if [ ! -d "node_modules" ]; then
    echo "Error: Frontend dependencies (node_modules) not found. Run npm install first." >&2
    kill $BACKEND_PID
    exit 1
fi

# 2. Wait for the backend's OpenAPI schema to be reachable, then
# regenerate ``frontend/generated/api/``. The frontend dev server
# imports the OpenAPI client at boot — without a fresh copy the
# imports are stale (or missing entirely on a fresh clone, since
# ``frontend/generated/`` is gitignored) and Vite will crash.
# 15 second timeout matches the headless-CI script in
# ``.agent/TEST.md`` so the two stay in sync.
timeout 15 bash -c 'until curl -s http://127.0.0.1:8000/openapi.json > /dev/null; do sleep 1; done'
npm run generate-api

# 3. Start the Vue frontend in the background
npm run dev -- --host &
FRONTEND_PID=$!

# Catch the shutdown signal from LinuxCNC when you close Axis
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" SIGINT SIGTERM EXIT

# Keep the script alive so the background processes keep running
wait

#python3 -m venv venv --system-site-packages

#[APPLICATIONS]
## LinuxCNC will run this script automatically after Axis starts
#APP = /home/linuxcnc/Downloads/LinuxCNC_UI/start_dev.sh

#chmod +x /home/linuxcnc/Downloads/LinuxCNC_UI/start_dev.sh
