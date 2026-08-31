#!/bin/bash

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ ! -d "$PROJECT_DIR" ]; then
    echo "Error: Project directory $PROJECT_DIR does not exist." >&2
    exit 1
fi

cd "$PROJECT_DIR/backend" || exit 1

# 1. Start the FastAPI backend in the background
# We bind to 127.0.0.1 because Nginx is handling the public network exposure
source venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

# 2. Dynamic Certificate Generation
cd "$PROJECT_DIR/frontend" || { kill $BACKEND_PID; exit 1; }
mkdir -p .cert

CURRENT_IP=$(hostname -I | awk '{print $1}')
echo "Detected IP: $CURRENT_IP"

# Mint a fresh certificate for localhost and the current dynamic IP
mkcert -cert-file .cert/localhost.pem -key-file .cert/localhost-key.pem localhost 127.0.0.1 "$CURRENT_IP"

# 3. Reload Nginx to apply the new certificate
# Nginx is already running in the background. We just tell it to grab the new files.
sudo systemctl reload nginx

echo "=========================================="
echo " CNC UI Backend Running!"
echo " Gateway: http://$CURRENT_IP"
echo " App:     https://$CURRENT_IP:8080"
echo "=========================================="

# Catch the shutdown signal from LinuxCNC when you close Axis
trap "kill $BACKEND_PID 2>/dev/null" SIGINT SIGTERM EXIT

# Keep the script alive so the backend keeps running
wait