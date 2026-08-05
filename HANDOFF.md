# Fix for Issue #82

## Plan

## Macro Support — Implementation Plan (Slice 1: Backend Core)

### Phase 0 — Research the three remaining context items

1. Read `frontend/src/router/index.js` (or equivalent) to capture the exact route registration convention (likely `createRouter({ history, routes })` with `path`/`name`/`component`/`meta`). Record route ordering, meta tags, and lazy-loading pattern so the `/macros` route and editor nav entry can be added in Phase 3 without surprises.
2. Read `frontend/src/views/Dashboard.vue` plus one or two sibling widgets under `frontend/src/components/` to confirm the existing card/grid layout primitives. Capture the wrapper class, grid utilities, and section-slot pattern so the new `MacroGrid.vue` slots in as a peer widget rather than being stylistically detached.
3. Read `backend/hardware/connection.py` and record the exact public API (`connection.send(...)`, `connection.recv(...)`, `connection.is_mock`, etc.) so the `CNCInterface` wrapper in `executor.py` routes `emit()`/`log()`/`get_pos()` through the same abstraction and the mock/real swap continues to work.

### Phase 1 — Backend core (`backend/macros/`)

4. `backend/macros/__init__.py` — `MacroStore` class:
   - `__init__(base_dir: Path)` resolving to a configurable directory (default `backend/macros/`).
   - `list() -> list[str]` returning sorted basenames without `.macro`.
   - `read(name) -> str`, `write(name, body)`, `delete(name)` with filename sanitisation: regex `^[A-Za-z0-9_-]+\.macro$` plus `Path(name).resolve().is_relative_to(base_dir)` as defense-in-depth; reject empty names and dot-prefixed names.
   - Module-level `logger = logging.getLogger(__name__)` per project convention.
5. `backend/macros/schemas.py` — Pydantic v2 models:
   - `MacroSummary(name: str, description: str | None = None)`
   - `MacroContent(name: str, body: str)`
   - `MacroRunRequest(parameters: dict[str, Any] | None = None)`
   - `MacroRunResponse(run_id: str, status: str)`
   - `MacroEvent(type: Literal["log","gcode","error"], payload: dict)` (reused by the WS stream in Phase 2).
6. `backend/macros/parser.py` — `parse(body: str) -> list[Segment]`:
   - `Segment` is a `dataclass` tagged union: `GCODEText` or `PythonBlock`.
   - Single-pass brace-balanced scanner (depth counter, not regex) so `{print("}")}` works; unmatched `{` raises `MacroParseError` with line number.
   - Each Python block is additionally passed through `ast.parse()` before `exec()` so syntax errors surface with readable line numbers before runtime.
   - `;` comments inside Python blocks are *not* stripped — Python handles them.
7. `backend/macros/executor.py` — execution engine:
   - `CNCInterface` class delegating to `backend.hardware.connection.connection` when available, falling back to `MockCNCInterface` (mirrors the project's existing mock pattern). Methods: `emit(gcode)`, `log(msg)`, `get_pos() -> dict`.
   - `macro_globals` populated with `cnc`, `math`, `time`, `params` (default empty dict), and `__builtins__`.
   - `run_macro(name, params=None) -> AsyncIterator[MacroEvent]` yields `MacroEvent(type="gcode", ...)`, `MacroEvent(type="log", ...)` for `cnc.log()` calls, and `MacroEvent(type="error", ...)` inside a `try/except` around each Python block.
   - `cnc.log()` is wired to `services.console_logger.get_console_logger()` so macro logs share the existing job-log stream.

### Phase 2 — Backend routing & wiring (next slice, scaffolded only)

8. `backend/macros/router.py` — `APIRouter(prefix="/api/macros", tags=["macros"])` with `GET /`, `GET /{name}`, `PUT /{name}`, `DELETE /{name}`, `POST /{name}/run`. Each endpoint carries `summary` and `description`.
9. Register the router in `backend/main.py` alongside the existing router includes (the `sys.path` bootstrap already in place makes the import path work).
10. Seed `backend/macros/probe_grid.macro` mirroring the issue example so the dashboard is not empty on first run.

### Phase 3 — Frontend (separate slice, deferred)

11. `frontend/src/stores/macros.js` — Pinia store with `macros`, `current`, `loading`, `error` refs and actions `fetchList`, `load`, `save`, `remove`, `run`. Use `storeToRefs()` and the existing `apiClient`.
12. `frontend/src/composables/useMacroLog.js` — WebSocket subscriber with cleanup in `onUnmounted`.
13. `frontend/src/components/MacroGrid.vue` — responsive Tailwind grid using `grid-cols-[repeat(auto-fill,minmax(theme(spacing.56),1fr))] gap-3` (per research), slotted into the existing dashboard widget row.
14. `frontend/src/components/MacroCodeEditor.vue` — `<script setup>` wrapper around `@codemirror/state` + `@codemirror/view` + `@codemirror/lang-python` + `@codemirror/legacy-modes` (G-code via `StreamLanguage`). Calls `editorView.destroy()` in `onUnmounted`.
15. `frontend/src/views/MacroEditor.vue` — sidebar list + editor + log console + Save/Run/Delete toolbar with confirmation on delete.
16. Register the `/macros` route in `frontend/src/router/` and add a nav entry consistent with the existing nav pattern.

### Conventions & safety guardrails

- 4-space indent, type hints, `logger = logging.getLogger(__name__)` in every new backend file.
- 2-space indent, double quotes, semicolons, `<script setup>`, Tailwind utilities only, `storeToRefs`, `onUnmounted` cleanup in every new frontend file.
- No `linuxcnc` import in feature code — all hardware access goes through `backend/hardware/connection.py`.
- Filename sanitisation + `Path.resolve().is_relative_to(...)` at the HTTP boundary.
- Jog watchdog (500 ms) and E-stop semantics are untouched; macros flow through `cnc.emit`.
- Sandbox is intentionally absent per the issue, but REST/WS validation prevents path traversal.

### Stop conditions

- After Phase 1 is drafted, return the one-paragraph summary and stop — orchestrator handles commit, tests, push, and PR.
- Phase 2 and Phase 3 are deferred to subsequent slices for orchestrator review.

## Implementation notes

--- Attempt 1 ---
Implemented the Phase 1 backend macro core in `backend/macros/`: added `MacroStore` with validated, path-safe file management; defined Pydantic schemas for macro content, execution requests, responses, and events; implemented a brace-balanced hybrid G-code/Python parser with syntax validation and line-aware errors; and added an async executor exposing `cnc.emit()`, `cnc.log()`, and `cnc.get_pos()` through the existing hardware and console logging abstractions. Phase 2 routing, frontend integration, seeded macros, and tests remain deferred as specified.
