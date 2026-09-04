# Repository Agent Guide

## Stack and structure

- Treat this repository as a monorepo with **three** Python processes and one Vue SPA:
  - `backend/common/` — shared library (settings store, event bus, DTOs, domain file services, hardware abstraction, exceptions). Never runs by itself; both apps below push it onto `sys.path` at boot.
  - `backend/machine/` — FastAPI app, port 8000. Everything that needs a *live* LinuxCNC session: telemetry WebSocket, NML state/MDI, jogging, program execution, tools/temperature/camera.
  - `backend/system/` — FastAPI app, port 8001. The always-running half: machine-config profile CRUD + template generation, program uploads, macro CRUD, version/update, and the LinuxCNC *process* lifecycle (start/stop/switch).
  - `frontend/` — Vue 3 + Vite SPA, TypeScript.
  - See [.agent/context/ARCHITECTURE.md](.agent/context/ARCHITECTURE.md) for the full picture, including which module id lives in which app and how nginx/Vite route between them.
- Backend: keep FastAPI routes in `backend/<app>/routers/`, service logic in `backend/<app>/services/`, shared/cross-app code in `backend/common/`. Do not add endpoints directly to either `main.py` — each app has its own `_MODULE_DOMAINS` table; add a router there.
- Frontend: there is **no dynamic module registry** — components are imported directly where they're used. Keep `frontend/src/App.vue` focused on layout. Put reusable panels and widgets in `frontend/src/components/<domain>/`, page-level composition in `frontend/src/views/`, shared state in Pinia stores under `frontend/src/stores/`, the generated OpenAPI client under `frontend/generated/api/` (gitignored, regenerate with `npm run generate-api` — needs both backends running), and generated machine commands in `frontend/src/config/gcodes.js`.

## Typing discipline (both languages)

- **Python: no bare `dict` in a signature or a stored value.** A `dict[str, Any]` (or worse, an untyped `dict`) hides the actual shape from every caller and from the type checker. Use a `TypedDict`, a `@dataclass`, or a Pydantic `BaseModel` instead — pick whichever the surrounding code already uses (Pydantic for request/response/settings, dataclasses for internal graphs like `MachineConfigGraph`). A `dict` is acceptable only as a genuinely dynamic, short-lived local (e.g. building up a JSON payload immediately before `json.dumps`), never as a parameter, return, or field type.
- **TypeScript: no `any`.** Prefer a concrete interface/type; when the shape is genuinely unknown at compile time (e.g. a raw fetch response before validation), use `unknown` and narrow it, not `any`. If you're reaching for `any` to silence a type error, that's a signal the surrounding types are wrong or missing — fix those instead of suppressing them.
- Type hints on every new Python function signature (parameters and return); avoid `Optional[...]` sprawl — prefer a default/sentinel that keeps call sites simple where it makes sense.
- These are new rules being retrofitted onto an existing codebase — you will find bare `dict`/`Any` in old code. Don't do a drive-by rewrite of unrelated code you're not otherwise touching, but never *add* a new bare `dict` or `any`, and tighten the type of anything you touch directly.

## Backend conventions

- Use 4-space indentation, PEP 8 naming, and focused functions. Use `logging` rather than `print` for diagnostics.
- Define routers with a prefix and `tags=[...]`; give every endpoint meaningful `summary` and `description` metadata.
- Use Pydantic models for validated request, response, and configuration data. Preserve the existing async FastAPI lifecycle and avoid blocking the event loop.
- Access LinuxCNC through `backend/common/hardware/Connection.py` (imported as `from hardware import ...`) so development remains compatible with the mock facade under `backend/common/hardware/mock/`; do not import the real `linuxcnc` module directly in feature code.
- Preserve machine-safety behavior. Continuous jog must retain the 500 ms backend watchdog and approximately 250 ms frontend keepalive cadence.
- Each app's own imports stay flat (`from services.X import Y`, `from core.settings_store import ...`) — both `main.py` files and every `tests/conftest.py` push `backend/common` onto `sys.path` ahead of the app's own directory. Don't invent a different import style for new files.
- Run each app's test suite as a **separate** `pytest` invocation (`backend/common/tests`, `backend/machine/tests`, `backend/system/tests`) — collecting more than one in the same process raises `ImportPathMismatchError` (all three directories are named `tests` with no shared package root).

## Frontend conventions

- Use Vue 3 Composition API with `<script setup lang="ts">` and keep components small and single-purpose.
- Use 2-space indentation. Match the existing quote/semicolon style in the file you're editing.
- Access shared state directly through Pinia rather than prop drilling. Use `storeToRefs()` when destructuring reactive store state, and instantiate another store inside an action (not at module scope) when cross-store communication could create circular initialization.
- Keep machine and G-code strings out of components and stores; add centralized constants or generator functions to `frontend/src/config/gcodes.js`.
- Prefer Tailwind CSS v4 utility classes and existing shared styles (see `frontend/src/ui/`). Avoid new component-scoped CSS when the design can be expressed with existing utilities.
- Route HTTP and WebSocket access through the existing service/store patterns and the Vite `/api` and `/ws` proxies (`frontend/vite.config.mjs` — routes to machine :8000 vs system :8001 by path prefix, mirroring nginx in production); clean up timers, sockets, and Three.js/ECharts resources when components unmount.

## Quality and scope

- Make the smallest change that solves the requested concern; do not mix in unrelated refactors or generated build output.
- Validate external input, return actionable API errors, and never weaken emergency-stop, jog-watchdog, file-path, or hardware-fallback safeguards.
- There is a real, substantial pytest suite (three separate suites — see above) and a frontend `node --test` suite. `vue-tsc --build` (`npm run typecheck`) gates the frontend, and `mypy` (`backend/mypy.ini`, run once per app) gates the backend for the bare-`dict`/generic rule specifically — see [.agent/TEST.md](.agent/TEST.md). Neither gate is `--strict`: mypy's `disable_error_code` list defers pre-existing type debt unrelated to that rule, and there is still no lint banning TypeScript's explicit `any` (code review only). See the technical-debt list in [.agent/HANDOFF.md](.agent/HANDOFF.md) § 2. Run every command in [.agent/TEST.md](.agent/TEST.md) before handoff.
