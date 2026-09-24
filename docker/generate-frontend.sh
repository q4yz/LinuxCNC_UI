#!/bin/bash
# Build-time only — runs inside the Docker builder stage.
#
# frontend/generated/api/ (the typed API client) is gitignored by
# design (see frontend/scripts/generate-api.mjs's own header) — it is
# generated FROM the two backends' live OpenAPI schemas, never
# committed. That means `vite build` cannot resolve a single
# `../../generated/api` import until both backends have actually run
# at least once. Mirrors install.sh's "Temporary Backend Spin-up"
# step exactly: start both in mock mode (no real linuxcnc/hal in this
# image — see hardware/Connection's own import fallback), wait for
# their OpenAPI schemas, generate the client, build, then always tear
# the temporary backends down (`trap ... EXIT` covers the failure
# path install.sh's own tail-of-script `kill` does not).
set -e

cd /app/backend/system
uvicorn main:app --host 127.0.0.1 --port 8001 > /tmp/system-build.log 2>&1 &
SYSTEM_PID=$!

cd /app/backend/machine
uvicorn main:app --host 127.0.0.1 --port 8000 > /tmp/machine-build.log 2>&1 &
MACHINE_PID=$!

cleanup() {
  kill "$SYSTEM_PID" "$MACHINE_PID" >/dev/null 2>&1 || true
  wait "$SYSTEM_PID" "$MACHINE_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[generate-frontend] Waiting for both backends to expose their OpenAPI schemas..."
if ! timeout 30 bash -c 'until curl -sf http://127.0.0.1:8001/openapi.json >/dev/null; do sleep 1; done'; then
  echo "[generate-frontend] system backend (:8001) never came up — see /tmp/system-build.log" >&2
  cat /tmp/system-build.log >&2
  exit 1
fi
if ! timeout 30 bash -c 'until curl -sf http://127.0.0.1:8000/openapi.json >/dev/null; do sleep 1; done'; then
  echo "[generate-frontend] machine backend (:8000) never came up — see /tmp/machine-build.log" >&2
  cat /tmp/machine-build.log >&2
  exit 1
fi

cd /app/frontend
npm run generate-api
npm run build
