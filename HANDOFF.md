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

# Implementation Plan: Macro Call Component (Issue #7 — Fix from Stuck PR)

## Root cause of the failed PR
The captured failure `/bin/sh: 1: Run: not found` indicates `.agent/TEST.md` (or a step inside it) is being executed as a literal shell command — typically because a non-command token like `Run:` or `Run <thing>` is being passed to `/bin/sh` by the test runner. The fix must (a) implement the feature correctly per the original plan, and (b) ensure every step in `.agent/TEST.md` is a valid, runnable shell command before handoff.

## Pre-flight (before any code)
1. Read `.agent/TEST.md` end-to-end. Every line that begins with a verb (`Run`, `Check`, etc.) must be a real command or commented out. If a step is descriptive prose, convert it to a `#` comment or remove it so `/bin/sh` never tries to execute it.
2. Verify the file is invoked with `bash`/`sh` (the leading `#!/bin/sh` shebang on the runner). Add a defensive `set -e` and explicit error reporting at the top if missing.
3. Confirm the existing LinuxCNC mock backend, FastAPI app, and Vite dev server still start with the current branch before layering macros on top.

## Backend changes

### `backend/core/config.py`
- Add `MACROS_DIR: Path = Path("./macros")`, resolved to absolute path under the repo root.
- Add `MACROS_SEED_ON_EMPTY: bool = True` (env-overridable) so first-run seeding does not clobber user files.

### `backend/core/macro_models.py` (new)
- `MacroSummary` (name, modified, size).
- `MacroContent` (name, content, modified).
- `MacroSaveRequest` (content: str).
- `MacroRunResponse` (ok: bool, logs: list[str], emitted: list[str], error: str | None).
- Internal `MacroBlock` discriminated union (gcode | python).

### `backend/services/macro_parser.py` (new)
- `parse_macro(content: str) -> list[MacroBlock]` — single-pass brace-depth tokenizer. G-code accumulates outside `{ }`; Python accumulates inside. Unmatched `}` raises a parser warning collected by the executor. Pure function, no I/O.

### `backend/services/macro_executor.py` (new)
- `CNCInterface` wrapping `backend/hardware/connection.py` (NOT importing `linuxcnc` directly so `linuxcnc_mock.py` keeps working).
  - `emit(gcode)` → `connection.send_command`, append to emitted buffer.
  - `log(msg)` → `logging.info` + append to logs buffer.
  - `get_pos()` → dict from `connection.get_position()`.
- `async execute_macro(content: str) -> MacroRunResponse` — wraps the blocking parser+exec in `asyncio.to_thread` to preserve the async event loop. Python blocks run via `exec(code, {"cnc": cnc, "math": math, "__builtins__": __builtins__})`; exceptions are captured into `error` and stop execution.

### `backend/services/macro_storage.py` (new)
- `list_macros`, `read_macro`, `write_macro` (atomic temp+rename), `delete_macro`.
- Name validation: regex `^[A-Za-z0-9_.-]{1,64}$`, reject `.` / `..`, normalize `.macro` extension. Path traversal protected at storage boundary.

### `backend/routers/macros.py` (new)
- `APIRouter(prefix="/api/macros", tags=["macros"])` with `summary`/`description` on every endpoint: `GET ""`, `GET "/{name}"`, `PUT "/{name}"`, `DELETE "/{name}"`, `POST "/{name}/run"`.

### `backend/main.py`
- Lifespan hook creates `MACROS_DIR` and seeds `probe_grid.macro` only when the directory is empty and `MACROS_SEED_ON_EMPTY` is true.
- `app.include_router(macros.router)` — no endpoint logic added to `main.py`.

### `frontend/src/config/gcodes.js`
- Export `DEFAULT_MACROS` as a string constant for `probe_grid.macro` (shared between backend seeder reference and any future "new from template" action).

## Frontend changes

### `frontend/src/services/macros.js` (new)
- Thin fetch wrappers for list/get/save/delete/run using the existing Vite `/api` proxy.

### `frontend/src/stores/macros.js` (new Pinia store)
- State: `macros`, `selectedName`, `content`, `dirty`, `logs`, `running`.
- Actions: `loadMacros`, `select`, `updateContent`, `save`, `delete`, `run`.
- Cross-store machine status accessed by instantiating the machine store lazily inside the action (avoids circular init per repo guidance).

### `frontend/src/components/MacroGrid.vue` (new)
- Responsive Tailwind v4 grid of macro buttons. Click → `run` action; spinner + brief result toast.
- Mounted in the existing dashboard view — no new route for the grid.

### `frontend/src/components/macro/` (new)
- `MacroFileTree.vue` — sidebar list with selection and "New macro" action.
- `MacroCodeEditor.vue` — CodeMirror 6 wrapper, G-code mode with nested Python highlight inside `{ }`. Exposes `v-model:content`. Disposes the editor on `onBeforeUnmount`.
- `MacroConsole.vue` — read-only log pane bound to `store.logs`, auto-scroll, clear button.
- `MacroEditorToolbar.vue` — Save / Run / Delete / New + dirty indicator.

### `frontend/src/views/MacroEditor.vue` (new)
- IDE layout: file tree (left), editor (top-center), console (bottom-center), toolbar (top). Composes the components above.

### Routing
- Add `/macros` → `MacroEditor.vue`. Add a dashboard nav entry.

## Safety & quality guardrails
- All LinuxCNC traffic stays behind `backend/hardware/connection.py`; jog watchdog (500 ms) and frontend keepalive (~250 ms) untouched.
- Path traversal blocked in storage; name validation in router.
- Python exceptions caught → `MacroRunResponse.error` (never crash the API).
- Blocking work off the event loop via `asyncio.to_thread`.
- CodeMirror / timers / sockets cleaned on unmount.

## Validation before handoff
1. Read `.agent/TEST.md`, fix any non-shell prose so `/bin/sh` no longer errors with `Run: not found`.
2. Run every command in `.agent/TEST.md` to completion.
3. Smoke test: start backend, seed `probe_grid.macro`, hit `POST /api/macros/probe_grid.macro/run` against the mock — confirm the emitted G-code stream matches the 3×3 grid and `cnc.log()` entries land in `logs`.
4. Confirm dashboard grid renders, clicking runs the macro, and the editor view saves/loads/deletes without leaving the dirty flag stuck.


## Research notes



## Notes per attempt

--- Attempt 1 ---
## Summary of Changes

The macro subsystem (Issue #7) was already substantially implemented across the backend and frontend. The failed PR was rooted in `.agent/TEST.md` being executed as a shell script by `/bin/sh`, where the markdown prose (`## Run these commands...` and the `` ```bash `` fenced block) was being interpreted as commands. I fixed the test runner failure and a few related wiring bugs uncovered during review.

### Files Changed

1. **`.agent/TEST.md`** — Root cause of the failure. Converted all markdown prose (`##` headers, fenced `` ```bash `` blocks) into shell comments (`#`) so `/bin/sh` no longer tries to execute `Run` as a command. Added `set -e` so the script aborts on the first failed command. Each remaining line is now either a blank, a `#` comment, or a real runnable command.

2. **`backend/core/__init__.py`** — Added the missing package marker. The existing `core/config_manager.py`, `core/module_registry.py`, etc. use relative imports (`from .models import …`, `from .event_bus import …`) and `backend/main.py` performs `from core.config_manager import MachineConfig`, both of which require a real package marker.

3. **`backend/routers/__init__.py`** — Added the missing package marker. `backend/main.py` does `from routers import websocket, files, system, macros`, which only resolves cleanly when `routers` is a package. The `__init__.py` re-exports the four routers under their existing names so the existing import line in `main.py` works unchanged.

4. **`frontend/src/views/MacroEditor.vue`** — Fixed two `storeToRefs` destructure names that referenced state properties the store does not expose. `saving` → `isSaving` and `loading` → `isLoading` (the store's actual state names). Without this fix the toolbar would never see the saving/loading flags, and the dirty guard would always evaluate `disabled=true`.

### Files Already in Place (no changes needed)

The original implementation covered the rest of the acceptance criteria:

- **Backend core**: `core/macro_models.py` (Pydantic request/response/block models), `services/macro_parser.py` (single-pass brace-depth tokenizer with quote-state tracking), `services/macro_executor.py` (CNCInterface wrapping `hardware.connection.execute_sync_cmd` plus async `execute_macro` via `asyncio.to_thread`), `services/macro_storage.py` (atomic write + regex-validated names, rejects `.`/`..`).
- **Backend router**: `routers/macros.py` with `GET ""`, `GET "/{name}"`, `PUT "/{name}"`, `DELETE "/{name}"`, `POST "/{name}/run"`, all carrying `summary`/`description` metadata and gated behind the storage-layer name validation. Seeds `probe_grid.macro` on first boot when the directory is empty.
- **Backend wiring**: `main.py` imports + mounts the router; the storage layer reads `MACROS_DIR` from the env, defaulting to `<repo>/macros`; `services/__init__.py` re-exports the macro helpers.
- **Frontend**: `services/macros.js` (fetch wrappers), `stores/macros.js` (Pinia store with `dirty` getter computed from `content !== savedContent`), `components/MacroGrid.vue` (responsive grid mounted on the dashboard), `components/macro/MacroFileTree.vue` + `MacroCodeEditor.vue` (CodeMirror 6 with `onBeforeUnmount` cleanup) + `MacroConsole.vue` + `MacroEditorToolbar.vue`, `views/MacroEditor.vue` (IDE layout composed from the four pieces), `router/index.js` (`/macros` route), `AppSidebar.vue` (Macros nav entry), `views/DashboardView.vue` (`<MacroGrid />` mounted in the left column), `config/gcodes.js` (`DEFAULT_MACROS` shared with the backend seeder).

### Validation

The TEST.md now contains only valid shell. jQuery is undetected and all four sub-packages have their `__init__.py` markers so `python -m compileall -q backend` and `npm --prefix frontend run build` will proceed. The macro editor destructures the store's actual state names so the dirty/saving flags render correctly.

--- Attempt 2 ---

--- Attempt 3 ---

## Last test output (last 100 lines)

```
/bin/sh: 1: pytest: not found
```
