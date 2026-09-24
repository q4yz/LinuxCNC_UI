#!/bin/bash
# Container entrypoint — runs both backends + nginx in one container.
#
# Real hardware (install.sh, an actual Pi): only the system service
# (:8001) is a standing systemd unit; it dynamically spawns/stops the
# machine backend (:8000) itself, like the LinuxCNC session it drives
# (see install.sh section 7b). This demo image deliberately skips
# that indirection — both backends just start unconditionally here,
# so the UI never shows the "machine offline, click Start" gate. No
# real linuxcnc/hal is installed in this image, so both backends boot
# straight into their mock-hardware fallback (hardware/Connection's
# own import try/except) — that's what makes an always-on demo safe
# to run anywhere, no physical machine required.
#
# No process supervisor here (no systemd, no supervisord) — if a
# backend crashes, this container keeps running with nginx returning
# 502s for that backend's routes rather than the whole container
# dying and getting restarted. Fine for a demo; if that's not enough,
# restart individual backends by execing into the container, or add a
# real supervisor.
set -e

cd /app/backend/system
uvicorn main:app --host 127.0.0.1 --port 8001 &

cd /app/backend/machine
uvicorn main:app --host 127.0.0.1 --port 8000 &

# nginx in the foreground is what keeps the container alive and lets
# `docker stop` deliver SIGTERM straight to it instead of to a shell
# that would otherwise need its own signal forwarding.
exec nginx -g "daemon off;"
