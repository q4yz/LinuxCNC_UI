#!/bin/bash

# Give Axis and the HAL 2 seconds to fully boot up before we connect
sleep 2

# Go to your project directory
cd /home/linuxcnc/Downloads/LinuxCNC_UI/backend

# 1. Start the FastAPI backend in the background
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

cd /home/linuxcnc/Downloads/LinuxCNC_UI/frontend
# 2. Start the Vue frontend in the background
npm run dev -- --host &
FRONTEND_PID=$!

# 3. Open the browser to your dev server
sleep 2
xdg-open http://localhost:5173 &

# Catch the shutdown signal from LinuxCNC when you close Axis
trap "kill $BACKEND_PID $FRONTEND_PID" SIGINT SIGTERM EXIT

# Keep the script alive so the background processes keep running
wait

#[APPLICATIONS]
## LinuxCNC will run this script automatically after Axis starts
#APP = /home/linuxcnc/Downloads/LinuxCNC_UI/start_dev.sh

#chmod +x /home/linuxcnc/Downloads/LinuxCNC_UI/start_dev.sh