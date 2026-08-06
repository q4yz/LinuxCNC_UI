# LinuxCNC Web UI

A modern, high-performance web interface for LinuxCNC, heavily inspired by "Fluidd" and "Mainsail".

This project provides a complete, decoupled architecture that lets you monitor and control your LinuxCNC machine from any browser, complete with a real-time 3D WebGL Toolpath viewer.

> **🤖 AI agents:** Your entry point is [`.agent/context/hub.md`](.agent/context/hub.md). This README is for human developers.
>
> The hub-and-spoke docs (`.agent/context/hub.md` → `VISION.md`, `ARCHITECTURE.md`, `LESSONS_LEARNED.md`) are the curated context the AI agent should read first. Do not browse the repo directly; the spokes already encode the context you need.

---

## Audience

This README is for **human developers**. If you are an AI agent, jump to [`.agent/context/hub.md`](.agent/context/hub.md).

## What this is

A monorepo with two services:

- **`backend/`** — Python 3 FastAPI application exposing REST endpoints and a high-speed (10 Hz) WebSocket telemetry stream, with a robust mock hardware layer for local development on non-Linux machines.
- **`frontend/`** — Vue 3 + Pinia SPA with a Three.js 3D toolhead viewer, Tailwind UI, and a pluggable module system for adding features without touching the application shell.

## Quick Start

### 1. Start the Backend

Open a terminal, navigate to the `backend/` folder, install the Python requirements, and start the API:

```bash
cd backend
python -m venv venv
# Windows: .\venv\Scripts\activate | Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
python main.py
```

The backend listens on `http://0.0.0.0:8000`. Swagger UI is at `http://localhost:8000/docs`.

### 2. Start the Frontend

Open a **second** terminal, navigate to the `frontend/` folder, install the npm modules, and start the Vite dev server:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser. The Vite proxy automatically routes `/api` and `/ws` traffic to the backend on port 8000, so the SPA sees a single origin.

*For detailed installation instructions, see the individual READMEs in the `backend/` and `frontend/` directories.*

## Architecture

The monorepo layout:

| Folder | Purpose |
|--------|---------|
| `backend/` | FastAPI app, hardware abstraction layer, pluggable modules under `backend/modules/`. |
| `frontend/` | Vue 3 SPA, pluggable modules under `frontend/src/modules/`. |
| `.agent/context/` | Hub-and-spoke context docs (the AI agent's entry point). |
| `.agent/` | AI agent contracts, the module system state, and the GraphLLM orchestrator's operating manual. |
| `scripts/` | Dev utilities (e.g. the local MiniMax M3 proxy used by the editor's AI tooling). |
| `nc_files/`, `gcodes/`, `machine_config/` | Operator data — uploaded G-code, profile definitions, and the live active configuration. |

The canonical architecture document is **[`.agent/context/ARCHITECTURE.md`](.agent/context/ARCHITECTURE.md)**. It covers the module registry graph, the backend ↔ frontend contract, the event bus, the State Facade, and the safety watchdogs.

## Contributing

### Before you write code

1. Read [`.agent/context/VISION.md`](.agent/context/VISION.md) — project goals and what we are not building.
2. Read [`.agent/context/ARCHITECTURE.md`](.agent/context/ARCHITECTURE.md) — the technical structure.
3. Skim [`.agent/context/LESSONS_LEARNED.md`](.agent/context/LESSONS_LEARNED.md) — past mistakes and tripwires (Pinia store IDs, eager imports, venv cache, the jog watchdog, hardcoded G-code).

### Coding conventions

| Area | Convention |
|------|------------|
| Backend | PEP 8, 4-space indentation, type hints on public functions, use `logging` (not `print`), Pydantic models for every request / response, Routers with `prefix` + `tags=[...]`, summary/description metadata on every endpoint. |
| Frontend | Vue 3 Composition API with `<script setup>`, 2-space indentation, double quotes, semicolons, Pinia stores with `storeToRefs()` when destructuring, Tailwind utility-first styling. |
| Hardware access | Always go through `backend/hardware/connection.py`. Never import `linuxcnc` directly in feature code. |
| G-code | All G-code helpers live in `frontend/src/config/gcodes.js`. Never hardcode G-code strings in components. |
| Modules | Every feature lives under `backend/modules/<id>/` and `frontend/src/modules/<id>/`. Pinia store IDs use the `module_<id>` template. |

### Testing

| Layer | Command |
|-------|---------|
| Backend syntax | `python -m compileall -q backend` |
| Backend tests | `python -m pytest backend/tests` |
| Frontend tests | `node --test frontend/tests/*.mjs` |
| Frontend build | `npm --prefix frontend run build` |

The CI / orchestrator runs the same surface via `.agent/TEST.md`. The test suite is the contract — when the source changes shape, update the tests in the same commit.

### Adding a new module

1. Create `backend/modules/<id>/` with `module.py`, `router.py`, `settings.py`.
2. Create `frontend/src/modules/<id>/` with `manifest.js`, `index.js`, `store.js`, and your components.
3. Update the manifests so the IDs match.
4. Add backend tests in `backend/tests/test_<id>_module.py` and frontend tests in `frontend/tests/test-<id>-module.mjs`.
5. Verify the full surface: `python -m compileall -q backend && python -m pytest backend/tests && node --test frontend/tests/*.mjs && npm --prefix frontend run build`.

## License

See [`LICENSE`](LICENSE).



