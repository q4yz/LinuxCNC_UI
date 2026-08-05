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

# 1. Start the FastAPI backend in the background
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

cd "$PROJECT_DIR/frontend" || exit 1

# Safety Check 3: Ensure node_modules exists for the frontend
if [ ! -d "node_modules" ]; then
    echo "Error: Frontend dependencies (node_modules) not found. Run npm install first." >&2
    kill $BACKEND_PID
    exit 1
fi

# 2. Start the Vue frontend in the background
npm run dev -- --host &
FRONTEND_PID=$!

# 3. Open the browser to your dev server
sleep 2
xdg-open http://localhost:5173 &

# Catch the shutdown signal from LinuxCNC when you close Axis
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" SIGINT SIGTERM EXIT

# Keep the script alive so the background processes keep running
wait

#[APPLICATIONS]
## LinuxCNC will run this script automatically after Axis starts
#APP = /home/linuxcnc/Downloads/LinuxCNC_UI/start_dev.sh

#chmod +x /home/linuxcnc/Downloads/LinuxCNC_UI/start_dev.sh