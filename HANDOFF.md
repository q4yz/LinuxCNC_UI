# Fix for Issue #82

## Plan

## Macro Support — Implementation Plan

### Research still needed
Confirm before coding:
1. Whether `monaco-editor` or `codemirror` is already in `frontend/package.json` (research notes show the read started but result not included). Pick the one already present; if neither, default to CodeMirror 6 (lighter, MIT, matches the "smallest diff" rule).
2. Existing router structure (`frontend/src/router/`) to know where to add the `/macros` route.
3. Existing dashboard view layout (`frontend/src/views/Dashboard.vue` or similar) so the macro grid reuses existing card/grid utilities instead of inventing new ones.
4. The exact API of `backend/hardware/connection.py` so the mock `cnc` object and the executor route G-code through the same abstraction used everywhere else (not direct `linuxcnc` import).

### Backend (`backend/`)
1. **Storage layer** — add `backend/macros/__init__.py` and a `MacroStore` helper that reads/writes/deletes `*.macro` files under a configurable directory (default `backend/macros/`). Provide `list()`, `read(name)`, `write(name, body)`, `delete(name)` with filename sanitisation (alphanumerics, `_`, `-`, `.macro`).
2. **Schemas** — `backend/macros/schemas.py` with Pydantic models: `MacroSummary(name, description)`, `MacroContent(name, body)`, `MacroRunRequest(parameters: dict | None)`, and standard error responses.
3. **Parser** — `backend/macros/parser.py` exposing `parse(body: str) -> list[Segment]` where `Segment` is a tagged union `{kind: "gcode", text}` or `{kind: "python", code}`. Brace-balanced scan (not regex) so `{ print("}") }` works; treat unmatched `{` as a parse error.
4. **Executor** — `backend/macros/executor.py`:
   - `CNCInterface` class wrapping `backend/hardware/connection.py` (real) or `MockCNCInterface` (used in tests/when no hardware). Methods: `emit(gcode)`, `log(msg)`, `get_pos() -> dict`.
   - `macro_globals` dict injected into every Python block: `cnc`, `math` (real `math` module), `time`, plus a per-run `params` dict for the V2 modal feature.
   - `run_macro(name)` async generator that yields structured events `{type: "log"|"gcode"|"error", payload}` so the frontend console can stream them via WebSocket (reuse existing WS pattern).
   - Python blocks run via `exec(code, macro_globals)`; G-code segments are fed to `cnc.emit()`.
5. **Router** — `backend/macros/router.py` with prefix `/api/macros`, tags=`["macros"]`:
   - `GET /` → list
   - `GET /{name}` → content
   - `PUT /{name}` → save
   - `DELETE /{name}` → delete
   - `POST /{name}/run` → execute (returns the run id; execution streams over existing `/ws/jobs` or a new `/ws/macros` channel — confirm WS pattern first).
6. **Wiring** — register the router in the FastAPI app entry point alongside other routers. Add `module-level logger = logging.getLogger(__name__)` in every new file.
7. **Seed data** — drop one demo `probe_grid.macro` mirroring the issue example so the dashboard isn't empty on first run.

### Frontend (`frontend/src/`)
1. **Pinia store** — `frontend/src/stores/macros.js` (module-level) exposing: `macros` (ref list), `current` (ref of loaded macro body), `loading`/`error` refs, and actions `fetchList`, `load(name)`, `save(name, body)`, `remove(name)`, `run(name, params?)`. Use the existing `apiClient` service for HTTP and follow the established `storeToRefs()` pattern.
2. **WebSocket hook** — small composable `useMacroLog(runId)` that subscribes to the macro execution channel, exposes a reactive `lines` array, and cleans up on `onUnmounted` (per the resource-cleanup rule).
3. **Dashboard widget** — `frontend/src/components/MacroGrid.vue` (reusable, single-purpose): responsive Tailwind grid of buttons, one per macro, click triggers `run()` via the store. Slotted into the existing Dashboard view where other widgets live — do not redesign the dashboard.
4. **Macro Editor view** — `frontend/src/views/MacroEditor.vue`:
   - Left sidebar: macro list with `+ New` button (uses same Tailwind utilities as other sidebars).
   - Center: code editor component (`<MacroCodeEditor>`) wrapping the chosen editor lib (Monaco or CodeMirror). Props: `modelValue`, emits `update:modelValue`.
   - Bottom: log console pane bound to `useMacroLog`.
   - Toolbar: Save / Run / Delete with confirmation on delete.
5. **Router** — register `/macros` route pointing to `MacroEditor.vue`; add a nav entry consistent with the existing nav pattern.
6. **Conventions check** — 2-space indent, double quotes, semicolons, `<script setup>`, Tailwind utilities only (no scoped CSS), Pinia via `storeToRefs`, resource cleanup in `onUnmounted`.

### Safety & conventions reminders
- Do **not** weaken jog watchdog or E-stop semantics; macros flow through `cnc.emit`, not a privileged path.
- Sandbox is intentionally absent per the issue — but still validate macro *filenames* at the HTTP boundary so path traversal is impossible.
- The mock `cnc` object must go through `backend/hardware/connection.py` so the LinuxCNC/mock swap continues to work.

### Suggested execution order
1. Confirm the four research items above.
2. Backend storage + parser + executor + mock `cnc` (testable in isolation).
3. Backend router + wire-up + seed macro.
4. Pinia store + HTTP/WS plumbing.
5. Dashboard widget.
6. Macro Editor view + code editor component + log pane.
7. Manual smoke check (orchestrator runs tests via `.agent/TEST.md`).

## Implementation notes

--- Attempt 1 ---

--- Attempt 2 ---
I added a `sys.path` bootstrap at the top of `backend/main.py` that injects the `backend/` directory (resolved via `Path(__file__).resolve().parent`) into `sys.path` before the module-level imports run. This mirrors the existing pattern in `backend/tests/conftest.py` (which does the same for pytest) so that the top-level imports `from core.config_manager import MachineConfig`, `from hardware.connection import connection`, `from services.console_logger import get_console_logger`, and `from routers import websocket, files, system` resolve when uvicorn launches the app as `backend.main:app`. The change is the minimum needed to clear the `ModuleNotFoundError: No module named 'core'` that blocked the orchestrator's `.agent/TEST.md` step that starts the backend to fetch `openapi.json`; the rest of the lifespan wiring, router includes, and `__main__` block are untouched, and the existing test run (240 passed) is unaffected because the conftest already adds the same path during pytest. No other files were modified, no tests were executed, and no commit was made.
