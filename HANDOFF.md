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

## Architecture Review & Implementation Plan — Issue #7 (Macro Call Component)

### Root-cause of prior failure
The last attempt's test output (`/bin/sh: 1: Run: not found`) indicates a shell script (likely in `.agent/TEST.md` or a CI helper) is invoking an executable literally named `Run` (capital R, no path). This is unrelated to the application logic and suggests a malformed shebang, a missing `set -e`/script entry, or a copy/paste artifact in a wrapper. The implementation plan below is correct; **the first action item is to fix that test-script invocation** before any code is touched, otherwise every run will fail regardless of correctness.

### Step-by-step plan

#### 0. Pre-flight (unblock CI)
- Inspect `.agent/TEST.md` and any helper scripts it calls.
- Replace the literal `Run` token with the intended command (e.g. `pytest`, `python -m …`, or the correct binary). Lowercase + add to PATH if needed.
- Re-run `.agent/TEST.md` on an unchanged checkout to confirm scripts execute before implementing the feature.

#### 1. Backend configuration
- `backend/core/config.py`: add `MACROS_DIR: Path` (default `./macros`, resolved to absolute, created in the existing FastAPI lifespan hook).
- Add `seed_example_macros: bool` env flag so first-run seeding is opt-in and never overwrites user files.

#### 2. Backend models (`backend/core/macro_models.py`)
- `MacroSummary { name, modified, size }`
- `MacroContent { name, content, modified }`
- `MacroSaveRequest { content }`
- `MacroRunResponse { ok, logs[], emitted[], error|null }`
- Internal `MacroBlock` union: `{kind:'gcode', text}` | `{kind:'python', code}`.

#### 3. Parser (`backend/services/macro_parser.py`)
- Pure function `parse_macro(content: str) -> list[MacroBlock]`.
- Single-pass brace-depth scan; flush gcode on `{`, flush python on `}`.
- Tolerate stray `}` (warn, do not raise) and nested `{}` inside Python string literals (track `"`/`'` state).
- Preserve leading indentation in python blocks.

#### 4. Executor (`backend/services/macro_executor.py`)
- `CNCInterface` wrapping `backend/hardware/connection.py`:
  - `emit(g)` → `connection.send_command(g)` + record
  - `log(msg)` → `logging.info` + append
  - `get_pos()` → `connection.get_position()`
- `async execute_macro(content) -> MacroRunResponse`:
  - Run parser + walk blocks via `asyncio.to_thread` so the event loop stays free.
  - For python blocks: `exec(code, globals_dict)` where `globals_dict = {"cnc": cnc, "math": math, "__builtins__": __builtins__}` is built per execution (no cross-run leakage).
  - Catch `Exception`, capture traceback into `error`, stop further execution.

#### 5. Storage (`backend/services/macro_storage.py`)
- `list_macros / read_macro / write_macro / delete_macro`.
- Name validation: regex `^[A-Za-z0-9_.-]{1,64}$`, reject `.`/`..`, normalize extension to `.macro`.
- Atomic write (`Path.replace` after temp file) to survive crashes mid-save.

#### 6. Router (`backend/routers/macros.py`)
- `APIRouter(prefix="/api/macros", tags=["macros"])`.
- Endpoints with `summary`+`description`:
  - `GET ""` list
  - `GET "/{name}"` fetch
  - `PUT "/{name}"` upsert
  - `DELETE "/{name}"` delete
  - `POST "/{name}/run"` execute
- Register in `backend/main.py` via `app.include_router(macros.router)` (never add endpoints directly to `main.py`).
- Seed `probe_grid.macro` from a constant on first run when the directory is empty and the seed flag is enabled.

#### 7. Frontend service (`frontend/src/services/macros.js`)
- `listMacros / getMacro / saveMacro / deleteMacro / runMacro` using the Vite `/api` proxy and the project's existing `fetch` wrapper.

#### 8. Pinia store (`frontend/src/stores/macros.js`)
- State: `macros`, `selectedName`, `content`, `dirty`, `logs`, `running`, `lastResult`.
- Actions: `loadMacros`, `select`, `updateContent`, `save`, `remove`, `run`.
- If `run` needs machine status, instantiate the machine store lazily inside the action to avoid circular init.

#### 9. Shared constants (`frontend/src/config/gcodes.js`)
- Export `DEFAULT_MACROS` containing the `probe_grid.macro` template so the backend seeder and any future "new from template" UI share a single source of truth.

#### 10. Dashboard widget (`frontend/src/components/MacroGrid.vue`)
- Tailwind v4 responsive grid; each button = macro name, optional last-run timestamp.
- Click → `run` action; inline spinner + transient result indicator.
- Mount from the existing dashboard view; no new route for the grid.

#### 11. Editor components (`frontend/src/components/macro/`)
- `MacroFileTree.vue` — sidebar list, selection, "New macro" button.
- `MacroCodeEditor.vue` — CodeMirror 6 wrapper, `v-model:content`, nested Python mode inside `{ }` via CodeMirror's nested-language support; dispose view on unmount.
- `MacroConsole.vue` — read-only log pane bound to `store.logs`, auto-scroll, clear button.
- `MacroEditorToolbar.vue` — Save / Run / Delete / New + dirty dot.

#### 12. Editor view (`frontend/src/views/MacroEditor.vue`)
- Layout: toolbar (top) · tree (left) · editor (center top) · console (center bottom).
- Composes the four sub-components; reads/writes through the Pinia store.

#### 13. Routing & navigation
- Add `/macros` route pointing to `MacroEditor.vue` in the existing router config.
- Add a dashboard nav entry linking to `/macros`.

#### 14. Safety & quality guardrails
- Execution only touches LinuxCNC through `backend/hardware/connection.py` (mock-compatible). E-stop, jog watchdog (500 ms backend / ~250 ms frontend), and file-path safeguards are untouched.
- Path traversal blocked at storage; name validation at router.
- Python failures surface as `MacroRunResponse.error` — never a 500.
- All I/O done via `asyncio.to_thread`.
- CodeMirror timers/listeners disposed on unmount.

#### 15. Acceptance-criteria mapping
- Dashboard grid + click-to-run → steps 7–10.
- Editor view (tree, editor, Save/Run/Delete) → steps 11–13.
- Hybrid parser + Python exec with injected `cnc` → steps 3–4.

#### 16. Validation
- Run **every** command listed in `.agent/TEST.md` after each step group.
- Manual smoke: load `probe_grid.macro`, click Run, confirm the console shows `cnc.log` lines and `emitted` contains the expected G-code stream via `linuxcnc_mock.py`.
- Confirm dashboard renders, editor opens, Save/Round-trip and Delete work, and a malformed macro returns `ok:false` with `error` populated.

### needs_research rationale
No external research required. The chosen stack pieces (FastAPI router, Pydantic v2 models, Vue 3 `<script setup>`, Pinia, CodeMirror 6 nested languages, Tailwind v4 grid utilities) are already in the repo or are standard, well-documented choices covered by the existing conventions. The PR's failure was a shell-script artifact, not a knowledge gap.

## Research notes



## Notes per attempt

--- Attempt 1 ---

--- Attempt 2 ---

--- Attempt 3 ---

## Last test output (last 100 lines)

```
Requirement already satisfied: pip in ./.venv/lib/python3.12/site-packages (26.2.1)
Requirement already satisfied: annotated-doc==0.0.4 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 1)) (0.0.4)
Requirement already satisfied: annotated-types==0.7.0 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 2)) (0.7.0)
Requirement already satisfied: anyio==4.13.0 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 3)) (4.13.0)
Requirement already satisfied: click==8.3.2 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 4)) (8.3.2)
Requirement already satisfied: colorama==0.4.6 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 5)) (0.4.6)
Requirement already satisfied: fastapi==0.136.0 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 6)) (0.136.0)
Requirement already satisfied: h11==0.16.0 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 7)) (0.16.0)
Requirement already satisfied: httptools==0.7.1 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 8)) (0.7.1)
Requirement already satisfied: idna==3.12 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 9)) (3.12)
Requirement already satisfied: pydantic==2.13.3 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 10)) (2.13.3)
Requirement already satisfied: pydantic_core==2.46.3 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 11)) (2.46.3)
Requirement already satisfied: python-dotenv==1.2.2 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 12)) (1.2.2)
Requirement already satisfied: PyYAML==6.0.3 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 13)) (6.0.3)
Requirement already satisfied: starlette==1.0.0 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 14)) (1.0.0)
Requirement already satisfied: typing-inspection==0.4.2 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 15)) (0.4.2)
Requirement already satisfied: typing_extensions==4.15.0 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 16)) (4.15.0)
Requirement already satisfied: uvicorn==0.45.0 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 17)) (0.45.0)
Requirement already satisfied: watchfiles==1.1.1 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 18)) (1.1.1)
Requirement already satisfied: websockets==16.0 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 19)) (16.0)
Requirement already satisfied: python-multipart==0.0.27 in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 20)) (0.0.27)
Requirement already satisfied: opencv-python-headless in ./.venv/lib/python3.12/site-packages (from -r backend/requirements.txt (line 21)) (5.0.0.93)
Requirement already satisfied: numpy>=2 in ./.venv/lib/python3.12/site-packages (from opencv-python-headless->-r backend/requirements.txt (line 21)) (2.5.1)

npm error code EUSAGE
npm error
npm error The `npm ci` command can only install with an existing package-lock.json or
npm error npm-shrinkwrap.json with lockfileVersion >= 1. Run an install with npm@5 or
npm error later to generate a package-lock.json file, then try again.
npm error
npm error Clean install a project
npm error
npm error Usage:
npm error npm ci
npm error
npm error Options:
npm error [--install-strategy <hoisted|nested|shallow|linked>] [--legacy-bundling]
npm error [--global-style] [--omit <dev|optional|peer> [--omit <dev|optional|peer> ...]]
npm error [--include <prod|dev|optional|peer> [--include <prod|dev|optional|peer> ...]]
npm error [--strict-peer-deps] [--foreground-scripts] [--ignore-scripts] [--no-audit]
npm error [--no-bin-links] [--no-fund] [--dry-run]
npm error [-w|--workspace <workspace-name> [-w|--workspace <workspace-name> ...]]
npm error [-ws|--workspaces] [--include-workspace-root] [--install-links]
npm error
npm error aliases: clean-install, ic, install-clean, isntall-clean
npm error
npm error Run "npm help ci" for more info
npm error A complete log of this run can be found in: /root/.npm/_logs/2026-08-05T14_48_22_321Z-debug-0.log
```
