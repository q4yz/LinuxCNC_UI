# Repository Agent Guide

## Stack and structure

- Treat this repository as a monorepo: `backend/` is a Python 3 FastAPI/Uvicorn service and `frontend/` is a Vue 3/Vite SPA written in JavaScript.
- Keep FastAPI routes in `backend/routers/`, shared models and configuration in `backend/core/`, hardware access in `backend/hardware/`, and service logic in `backend/services/`. Do not add endpoints to `backend/main.py`.
- Keep `frontend/src/App.vue` focused on layout. Put reusable panels and widgets in `frontend/src/components/`, page-level composition in `frontend/src/views/`, shared state in Pinia stores under `frontend/src/stores/`, API calls in `frontend/src/services/`, and generated machine commands in `frontend/src/config/gcodes.js`.

## Backend conventions

- Use 4-space indentation, PEP 8 naming, type hints where practical, and focused functions. Use `logging` rather than `print` for diagnostics.
- Define routers with a prefix and `tags=[...]`; give every endpoint meaningful `summary` and `description` metadata.
- Use Pydantic models for validated request, response, and configuration data. Preserve the existing async FastAPI lifecycle and avoid blocking the event loop.
- Access LinuxCNC through `backend/hardware/connection.py` so development remains compatible with `linuxcnc_mock.py`; do not import the real `linuxcnc` module directly in feature code.
- Preserve machine-safety behavior. Continuous jog must retain the 500 ms backend watchdog and approximately 250 ms frontend keepalive cadence.

## Frontend conventions

- Use Vue 3 Composition API with `<script setup>` and keep components small and single-purpose.
- Use 2-space indentation, double quotes, and semicolons in JavaScript to match the existing source.
- Access shared state directly through Pinia rather than prop drilling. Use `storeToRefs()` when destructuring reactive store state, and instantiate another store inside an action when cross-store communication could create circular initialization.
- Keep machine and G-code strings out of components and stores; add centralized constants or generator functions to `frontend/src/config/gcodes.js`.
- Prefer Tailwind CSS v4 utility classes and existing shared styles. Avoid new component-scoped CSS when the design can be expressed with existing utilities.
- Route HTTP and WebSocket access through the existing service/store patterns and the Vite `/api` and `/ws` proxies; clean up timers, sockets, and Three.js/ECharts resources when components unmount.

## Quality and scope

- Make the smallest change that solves the requested concern; do not mix in unrelated refactors or generated build output.
- Validate external input, return actionable API errors, and never weaken emergency-stop, jog-watchdog, file-path, or hardware-fallback safeguards.
- No project lint or formal test suite is currently configured. Follow the established formatting above and run every command in `.agent/TEST.md` before handoff.
