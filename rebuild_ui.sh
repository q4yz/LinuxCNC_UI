#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
UI_DIST_DIR="$PROJECT_DIR/frontend/dist"
# Update this variable with the exact name of your systemd service
BACKEND_SYSTEM_SERVICE="linuxcnc-ui-system.service"

echo "Rebuilding UI in: $PROJECT_DIR"

# --- 1. Dump both services' OpenAPI schemas ---
# The frontend's typed API client is generated from BOTH services'
# merged OpenAPI schema (frontend/scripts/generate-api.mjs +
# merge-openapi.mjs). backend/dump_openapi.py reads each app's schema
# in-process — no server is started, so nothing answers on
# :8000/:8001 while the real services are down. (Temporary backends on
# the real ports made the UI's update screen think the system was back.)
echo "Dumping the API schemas (no backend is started)..."

# Activate the shared virtual environment
source "$PROJECT_DIR/backend/venv/bin/activate"

SCHEMA_DIR="$(mktemp -d)"
trap 'rm -rf "$SCHEMA_DIR"' EXIT
python "$PROJECT_DIR/backend/dump_openapi.py" machine "$SCHEMA_DIR/machine.json"
python "$PROJECT_DIR/backend/dump_openapi.py" system "$SCHEMA_DIR/system.json"
# ------------------------------------

# --- 2. Build the Frontend ---
cd "$PROJECT_DIR/frontend"

echo "Generating API client..."
OPENAPI_FILE="$SCHEMA_DIR/machine.json" OPENAPI_FILE_SYSTEM="$SCHEMA_DIR/system.json" npm run generate-api

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
sudo /bin/systemctl restart "$BACKEND_SYSTEM_SERVICE"

# --- 5. Reload Nginx ---
echo "Reloading Nginx..."
sudo /bin/systemctl reload nginx

echo "Build and reload complete! Nginx is now serving the updated frontend and proxying to the fresh backend."