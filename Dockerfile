# LinuxCNC UI — demo image.
#
# Runs the full split backend (machine :8000 + system :8001, see
# .agent/HANDOFF.md / backend/*/main.py) plus the built frontend
# behind nginx in ONE container, on mock hardware (no real linuxcnc/
# hal installed here — both services fall back to their mock facade
# automatically, see backend/common/hardware/Connection/core.py).
# This is a containerized version of install.sh's real-Pi deployment
# — same nginx routing (docker/nginx.conf), same "boot both backends
# to generate the frontend's typed API client" build step
# (docker/generate-frontend.sh) — with the hardware-specific pieces
# (mkcert/HTTPS, ustreamer camera service, systemd units, the
# system-service-spawns-machine-backend indirection) dropped; see
# docker/entrypoint.sh for what replaces that last one.
#
# Build:  docker build -t linuxcnc-ui-demo .
# Run:    docker run -p 8080:80 linuxcnc-ui-demo
# Then:   http://localhost:8080
#
# The host port MUST stay 8080 (or 80/443/5173/4173) — frontend/src/
# services/apiClient.ts only treats that exact port allowlist as
# same-origin and lets nginx proxy /api for it; any other host port
# makes the frontend call `<hostname>:8000` directly instead, which
# is unreachable from outside the container (verified live: -p
# 18080:80 breaks every API call this way). Need a different external
# port? Put a reverse proxy in front of this container instead of
# changing the mapping.

# ---------------------------------------------------------------------------
# Stage 1: builder — installs both toolchains, builds the frontend
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Backend deps first (own layer — changes far less often than source).
COPY backend/requirements.txt backend/requirements-machine.txt backend/requirements-system.txt backend/
RUN pip install --no-cache-dir \
        -r backend/requirements-machine.txt \
        -r backend/requirements-system.txt

COPY backend/ backend/

# Frontend source, then deps. Not split into a package.json-only
# layer for caching — this repo's `postinstall` hook
# (frontend/scripts/generate-api.mjs) needs its own script file
# present the moment `npm install` runs, so `scripts/` has to already
# be copied in; simplest to just copy all of `frontend/` first.
COPY frontend/ frontend/
# `npm install`, not `npm ci` — this repo's package-lock.json is
# currently out of sync with package.json (missing optional Rollup
# native deps like @emnapi/core), which makes `npm ci`'s strict
# lockfile check fail outright. `npm install` self-heals instead;
# swap back to `npm ci` once the lockfile is regenerated and
# committed clean.
RUN cd frontend && npm install

# Boot both backends (mock hardware), generate the typed API client
# from their live OpenAPI schemas, build the SPA, tear the temporary
# backends down. See docker/generate-frontend.sh for why this step
# has to exist at all — frontend/generated/api/ is gitignored, not a
# committed artifact.
COPY docker/generate-frontend.sh docker/generate-frontend.sh
RUN bash docker/generate-frontend.sh

# ---------------------------------------------------------------------------
# Stage 2: runtime — lean image, no Node (only needed to build the SPA)
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        nginx curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt backend/requirements-machine.txt backend/requirements-system.txt backend/
RUN pip install --no-cache-dir \
        -r backend/requirements-machine.txt \
        -r backend/requirements-system.txt

COPY backend/common backend/common
COPY backend/machine backend/machine
COPY backend/system backend/system

# Demo seed content — example machine profiles + a few real NGC files
# so the demo has something to show immediately, matching local dev.
COPY machine_config machine_config
COPY nc_files nc_files

COPY --from=builder /app/frontend/dist /app/frontend/dist

COPY docker/nginx.conf /etc/nginx/sites-available/linuxcnc-ui
RUN rm -f /etc/nginx/sites-enabled/default \
    && ln -s /etc/nginx/sites-available/linuxcnc-ui /etc/nginx/sites-enabled/linuxcnc-ui

COPY docker/entrypoint.sh docker/entrypoint.sh
RUN chmod +x docker/entrypoint.sh

EXPOSE 80

ENTRYPOINT ["/app/docker/entrypoint.sh"]
