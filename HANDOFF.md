# AI STUCK - Issue #7

The automated agent was unable to make the test suite pass after 3 attempts. The branch below contains the most recent attempt and the captured failure logs.

## Issue

title:	Issue #7: [Feature] Add Macro Call Component
state:	OPEN
author:	q4yz (Albert)
labels:	ai:in-progress
comments:	0
assignees:	
projects:	
milestone:	
issue-type:	
parent:	
sub-issues:	
sub-issues-completed:	
blocked-by:	
blocking:	
number:	7
--
Users need a quick way to execute and manage predefined LinuxCNC subroutines (macros) directly from the web UI. Drawing inspiration from Mainsail's macro panel, this feature will introduce a dashboard component for one-click execution and a dedicated editor view for writing custom macros.

To give users maximum flexibility, the macros will use a PHP-style templating approach: the base language is standard G-code, but users can open Python execution blocks using { ... } brackets to inject logic, loops, or complex calculations.

Security Note: Security and sandboxing are not a concern for this environment. The Python blocks will run with full privileges to interact with the system and CNC backend.

✅ Acceptance Criteria
1. Dashboard Component (Execution View)
[ ] Create a frontend component for the main dashboard that fetches available macros from the backend.

[ ] Render each available macro as a clickable button in a responsive grid.

[ ] Clicking a button immediately executes the macro.

[ ] (Optional/V2) If a macro requires parameters, clicking the button opens a modal to input variables before execution.

2. Macro Editor (Management View)
[ ] Create a separate, dedicated "Macro Editor" view in the frontend.

[ ] Display a list/sidebar of all existing macros to select from.

[ ] Integrate a code editor component (e.g., Monaco Editor or CodeMirror) to edit the selected macro.

[ ] Provide "Save", "Run", and "Delete" actions within the editor view.

3. Backend Parser & Executor (Hybrid Python/G-Code)
[ ] Implement a backend parser that reads the macro file and separates standard G-code from Python blocks enclosed in { }.

[ ] Evaluate the Python blocks at runtime.

[ ] Inject predefined mock objects/methods into the Python environment so scripts can easily interact with LinuxCNC (see example below).

💻 Technical Implementation Details
The Hybrid Language Concept
Just like PHP embeds logic into HTML, this system embeds Python logic into G-code. The parser should treat everything outside of { } as standard G-code to be sent to LinuxCNC. Everything inside { } is evaluated as Python.

Example Macro (probe_grid.macro):

G-Code
; Standard G-Code initialization
G21 ; Set units to mm
G90 ; Absolute positioning
G0 Z10 ; Move safely above workpiece

; --- Python Logic Block ---
{
    # Example mock setup: 
    # 'cnc' is a globally injected object provided by the backend
    
    grid_size = 3
    spacing = 15.0

    for x in range(grid_size):
        for y in range(grid_size):
            x_pos = x * spacing
            y_pos = y * spacing
            
            # Use the injected object to emit G-code or call APIs
            cnc.emit(f"G0 X{x_pos} Y{y_pos}")
            cnc.emit("G38.2 Z-5 F100 ; Probe down")
            cnc.emit("G0 Z10 ; Retract")
            
            # Can also include raw python logic like logging
            cnc.log(f"Probed point {x}, {y}")
}

; Back to standard G-code
G0 X0 Y0
M2 ; End program
Mock Setup for Initial Development
To get the parser and execution working, inject a simple mock cnc object into the Python execution context (globals dict in exec()):

Python
# Backend Python snippet for the executor
class CNCInterface:
    def emit(self, gcode_str):
        print(f"[TO LINUXCNC] {gcode_str}")
        # In production: linuxcnc.command(gcode_str)
        
    def log(self, message):
        print(f"[MACRO LOG] {message}")
        
    def get_pos(self):
        return {"x": 0.0, "y": 0.0, "z": 10.0}

# The context provided to the macro's python blocks
macro_globals = {
    "cnc": CNCInterface(),
    "math": __import__("math")
}
🎨 UI/UX References
Dashboard: Should look similar to Mainsail's macro grid (clean, wrap-around buttons, easy to hit on a touchscreen).

Editor: A standard IDE-like view. A file tree on the left, code editor on the right, and a console/log output window at the bottom to see cnc.log() outputs.

## Plan

# Implementation Plan: Macro Call Component

## Overview
Introduce a macro subsystem spanning backend (parser, executor, storage, REST API) and frontend (dashboard grid + dedicated editor view) that supports a PHP-style hybrid of G-code and inline Python blocks. Execution flows through the existing `backend/hardware/connection.py` abstraction to remain compatible with `linuxcnc_mock.py`. No new endpoints are added to `backend/main.py`; everything goes through a dedicated router.

## Backend

### 1. Configuration & Models
- Extend `backend/core/config.py` with:
  - `MACROS_DIR: Path` (default `./macros`, resolved relative to project root, auto-created on startup via FastAPI lifespan hook).
- Add Pydantic models (new file `backend/core/macro_models.py` to avoid bloating existing models):
  - `MacroSummary { name: str, modified: datetime, size: int }`
  - `MacroContent { name: str, content: str, modified: datetime }`
  - `MacroSaveRequest { content: str }`
  - `MacroRunResponse { ok: bool, logs: list[str], emitted: list[str], error: str | None }`
  - Internal `MacroBlock` discriminated union: `{ kind: "gcode", text: str } | { kind: "python", code: str }`.

### 2. Parser Service — `backend/services/macro_parser.py`
- `parse_macro(content: str) -> list[MacroBlock]`:
  - Single-pass token scan tracking brace depth; characters outside `{`/`}` accumulate into a `gcode` block.
  - On entering `{`, flush pending gcode; on matching `}`, accumulate interior as a `python` block.
  - Ignore unmatched `}` with a parser warning (returned in `MacroRunResponse.logs`).
  - Preserve leading whitespace/indentation in Python blocks so users can indent naturally.
- Pure function, fully unit-friendly; no I/O.

### 3. Executor Service — `backend/services/macro_executor.py`
- `CNCInterface` class wrapping the hardware connection:
  - `emit(gcode: str)` → `connection.send_command(gcode)` (from `backend/hardware/connection.py`); record in `emitted` list.
  - `log(message: str)` → `logging.info` + append to execution log buffer.
  - `get_pos()` → returns dict from `connection.get_position()`.
- `async execute_macro(content: str) -> MacroRunResponse`:
  - Calls `parse_macro`.
  - Walks blocks: G-code blocks → call `cnc.emit` per non-empty, non-comment-only line.
  - Python blocks → `exec(code, globals_dict)` where `globals_dict = {"cnc": cnc, "math": math, "__builtins__": __builtins__}`.
  - Wrap each `exec` in `try/except Exception` to capture traceback into `error` and stop execution.
  - Run the blocking work via `asyncio.to_thread()` so the FastAPI event loop is preserved per repo conventions.
- `globals_dict` is constructed per execution so macros cannot leak state across runs.

### 4. Storage Service — `backend/services/macro_storage.py`
- `list_macros() -> list[MacroSummary]`
- `read_macro(name: str) -> MacroContent`
- `write_macro(name: str, content: str)` — atomic write (temp file + rename) to avoid corruption on crash.
- `delete_macro(name: str)`
- Strict name validation: regex `^[A-Za-z0-9_.-]{1,64}$`, reject path traversal, reject reserved names (`..`, `.`).
- File extension normalized to `.macro`.

### 5. Router — `backend/routers/macros.py`
- `APIRouter(prefix="/api/macros", tags=["macros"])`.
- Endpoints (all with `summary` + `description`):
  - `GET ""` → list macros.
  - `GET "/{name}"` → fetch content.
  - `PUT "/{name}"` → create/overwrite.
  - `DELETE "/{name}"` → delete.
  - `POST "/{name}/run"` → execute, return `MacroRunResponse`.
- Wire into `backend/main.py` via `app.include_router(macros.router)`.
- Ensure lifespan hook creates `MACROS_DIR` and seeds one example macro (`probe_grid.macro` from the issue) on first run when the directory is empty, gated by an env flag so it does not overwrite user files in production.

## Frontend

### 6. Service Layer — `frontend/src/services/macros.js`
- Thin wrappers around the API endpoints: `listMacros`, `getMacro`, `saveMacro`, `deleteMacro`, `runMacro`.
- Uses the existing `fetch`/base-URL pattern (Vite `/api` proxy) consistent with other services in the repo.

### 7. Pinia Store — `frontend/src/stores/macros.js`
- State: `macros`, `selectedName`, `content`, `dirty`, `logs`, `running`.
- Actions:
  - `loadMacros()`
  - `select(name)` — fetches content into `content`.
  - `updateContent(text)` — sets dirty flag.
  - `save()` / `delete()` / `run()`.
  - If `run()` needs machine status, instantiate the machine store lazily inside the action (per the repo's cross-store guidance).
- Use `storeToRefs` at consumer sites.

### 8. Dashboard Widget — `frontend/src/components/MacroGrid.vue`
- Responsive grid (Tailwind v4 utilities only) of macro buttons.
- Each button: label = macro name (filename without `.macro`), subtitle = last-run timestamp if available.
- Click → `runMacro` action; show inline spinner + brief result toast.
- Integrate into the existing dashboard view (no new route for the grid itself).

### 9. Editor Components (under `frontend/src/components/macro/`)
- `MacroFileTree.vue` — sidebar list of macros, selection state, "New macro" button.
- `MacroCodeEditor.vue` — wraps CodeMirror 6 (lighter than Monaco; better fit for a touchscreen UI). Exposes `v-model:content`. G-code mode with custom highlighting plus a nested Python mode inside `{ }` regions (CodeMirror's nested language support).
- `MacroConsole.vue` — read-only log pane bound to `store.logs`, with auto-scroll and a clear button.
- `MacroEditorToolbar.vue` — Save / Run / Delete / New actions, dirty indicator.

### 10. Editor View — `frontend/src/views/MacroEditor.vue`
- Layout: file tree (left), editor (center top), console (center bottom), toolbar (top).
- Composes the components above; reads/writes via the Pinia store.
- Cleans up CodeMirror instance on unmount (per repo guidance).

### 11. Routing
- Add `/macros` route pointing to `MacroEditor.vue` in the existing router config.
- Add a navigation entry from the dashboard.

### 12. Shared Constants — `frontend/src/config/gcodes.js`
- Export `DEFAULT_MACROS` containing the `probe_grid.macro` example as a string constant so the backend seeder and any future frontend "create macro from template" can share it.
- Keep all machine/G-code strings out of components and stores.

## Safety & Quality Guardrails
- Macro execution is gated through the same hardware connection abstraction used elsewhere; the existing E-stop and jog-watchdog paths are untouched.
- Path traversal protection at storage layer; name validation at router.
- Python execution failures are caught and surfaced via `MacroRunResponse.error` rather than crashing the API.
- Async execution via `asyncio.to_thread` to avoid blocking the event loop.

## Acceptance Criteria Mapping
- Dashboard grid + execute → steps 8 + 7 (`run` action).
- Editor view with file tree, code editor, Save/Run/Delete → steps 9 + 10.
- Backend parser separating G-code from `{ ... }` Python and evaluating Python with injected `cnc` object → steps 2 + 3.

## Testing & Validation
- Run every command in `.agent/TEST.md` before handoff.
- Manual smoke test against the included `probe_grid.macro` to confirm Python block iteration produces the expected G-code stream through the mock backend.
- Verify frontend console pane captures `cnc.log()` output during run.


## Research notes



## Notes per attempt

--- Attempt 1 ---

--- Attempt 2 ---

--- Attempt 3 ---

## Last test output (last 100 lines)

```
/bin/sh: 1: Run: not found
```
