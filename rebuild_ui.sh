#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
UI_DIST_DIR="$PROJECT_DIR/frontend/dist"
# Update this variable with the exact name of your systemd service
BACKEND_SYSTEM_SERVICE="linuxcnc-ui-system.service"

echo "Rebuilding UI in: $PROJECT_DIR"

# --- 1. Spin up both temporary backends ---
# The frontend's typed API client is generated from BOTH services'
# merged OpenAPI schema (frontend/scripts/generate-api.mjs +
# merge-openapi.mjs), so both need to be briefly reachable here.
echo "Temporarily starting both backends to generate API schemas..."

# Activate the shared virtual environment
source "$PROJECT_DIR/backend/venv/bin/activate"

cd "$PROJECT_DIR/backend/machine"
uvicorn main:app --host 127.0.0.1 --port 8000 > "$PROJECT_DIR/backend-machine.log" 2>&1 &
MACHINE_BACKEND_PID=$!

cd "$PROJECT_DIR/backend/system"
uvicorn main:app --host 127.0.0.1 --port 8001 > "$PROJECT_DIR/backend-system.log" 2>&1 &
SYSTEM_BACKEND_PID=$!

# CRITICAL: Ensure both backends are killed when this script exits, even if npm build fails
trap "kill $MACHINE_BACKEND_PID $SYSTEM_BACKEND_PID 2>/dev/null; wait $MACHINE_BACKEND_PID $SYSTEM_BACKEND_PID 2>/dev/null || true" EXIT

echo "Waiting for both backends to expose their OpenAPI schemas..."
timeout 15 bash -c 'until curl -s http://127.0.0.1:8000/openapi.json > /dev/null; do sleep 1; done'
timeout 15 bash -c 'until curl -s http://127.0.0.1:8001/openapi.json > /dev/null; do sleep 1; done'
# ------------------------------------

# --- 2. Build the Frontend ---
cd "$PROJECT_DIR/frontend"

echo "Generating API client..."
npm run generate-api

echo "Compiling Vite application..."
npm run build

# --- 3. Restore the Root CA for the popup ---
echo "Restoring Root CA to the dist directory..."
CA_ROOT="$HOME/.local/share/mkcert/rootCA.pem"

if [ -f "$CA_ROOT" ]; then
    cp "$CA_ROOT" "$UI_DIST_DIR/cnc-root.crt"
    chmod 644 "$UI_DIST_DIR/cnc-root.crt"
    echo "Root CA restored successfully."
else
    echo "Warning: Root CA not found at $CA_ROOT. The download button may not work."
fi

# --- 4. Restart Backend System Service ---
echo "Restarting the backend system service..."
# Note: You may need to run this script with sudo or ensure your user has NOPASSWD sudo rights for systemctl
sudo systemctl restart "$BACKEND_SYSTEM_SERVICE"

# --- 5. Reload Nginx ---
echo "Reloading Nginx..."
sudo systemctl reload nginx

echo "Build and reload complete! Nginx is now serving the updated frontend and proxying to the fresh backend."