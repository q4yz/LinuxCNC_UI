#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Rebuilding UI in: $PROJECT_DIR"

# --- 1. Spin up temporary backend ---
echo "Temporarily starting backend to generate API schema..."
cd "$PROJECT_DIR/backend"

# Activate the virtual environment
source venv/bin/activate

# Start uvicorn in the background
uvicorn main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

# CRITICAL: Ensure the backend is killed when this script exits, even if npm build fails
trap "kill $BACKEND_PID 2>/dev/null; wait $BACKEND_PID 2>/dev/null || true" EXIT

echo "Waiting for backend to expose OpenAPI schema..."
timeout 15 bash -c 'until curl -s http://127.0.0.1:8000/openapi.json > /dev/null; do sleep 1; done'
# ------------------------------------

# --- 2. Build the Frontend ---
cd "$PROJECT_DIR/frontend"

echo "Generating API client..."
npm run generate-api

echo "Compiling Vite application..."
npm run build

echo "Build complete! Nginx will now serve the updated files."