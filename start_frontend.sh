#!/bin/bash

PROJECT_DIR="/home/printnc/LinuxCNC_UI"

cd "$PROJECT_DIR/frontend" || exit 1

if [ ! -d "node_modules" ]; then
    echo "Error: Frontend dependencies not found. Run npm install." >&2
    exit 1
fi

# Wait for the backend (which LinuxCNC started) to be ready
timeout 15 bash -c 'until curl -s http://127.0.0.1:8000/openapi.json > /dev/null; do sleep 1; done'

# Generate the API clients
npm run generate-api

# Start the Vue frontend
npm run dev -- --host &
FRONTEND_PID=$!

# Kill the frontend when LinuxCNC closes
trap "kill $FRONTEND_PID 2>/dev/null" SIGINT SIGTERM EXIT

wait