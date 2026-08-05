# AI STUCK - Issue #70

The automated agent was unable to make the test suite pass after 3 attempts. The branch below contains the most recent attempt and the captured failure logs.

## Issue

title:	add macros
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
number:	70
--
Users need a quick way to execute and manage predefined LinuxCNC subroutines (macros) directly from the web UI. Drawing inspiration from Mainsail's macro panel, this feature will introduce a dashboard component for one-click execution and a dedicated editor view for writing custom macros.

To give users maximum flexibility, the macros will use a PHP-style templating approach: the base language is standard G-code, but users can open Python execution blocks using { ... } brackets to inject logic, loops, or complex calculations.

Security Note: Security and sandboxing are not a concern for this environment. The Python blocks will run with full privileges to interact with the system and CNC backend.

✅ Acceptance Criteria

Dashboard Component (Execution View)
[ ] Create a frontend component for the main dashboard that fetches available macros from the backend.
[ ] Render each available macro as a clickable button in a responsive grid.

[ ] Clicking a button immediately executes the macro.

[ ] (Optional/V2) If a macro requires parameters, clicking the button opens a modal to input variables before execution.

Macro Editor (Management View)
[ ] Create a separate, dedicated "Macro Editor" view in the frontend.
[ ] Display a list/sidebar of all existing macros to select from.

[ ] Integrate a code editor component (e.g., Monaco Editor or CodeMirror) to edit the selected macro.

[ ] Provide "Save", "Run", and "Delete" actions within the editor view.

Backend Parser & Executor (Hybrid Python/G-Code)
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

Example mock setup:
'cnc' is a globally injected object provided by the backend
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

Backend Python snippet for the executor
class CNCInterface:
def emit(self, gcode_str):
print(f"[TO LINUXCNC] {gcode_str}")

In production: linuxcnc.command(gcode_str)
def log(self, message):
print(f"[MACRO LOG] {message}")

def get_pos(self):
return {"x": 0.0, "y": 0.0, "z": 10.0}
The context provided to the macro's python blocks
macro_globals = {
"cnc": CNCInterface(),
"math": import("math")
}
🎨 UI/UX References
Dashboard: Should look similar to Mainsail's macro grid (clean, wrap-around buttons, easy to hit on a touchscreen).

Editor: A standard IDE-like view. A file tree on the left, code editor on the right, and a console/log output window at the bottom to see cnc.log() outputs.

## Plan

## Plan: Unstick PR for Issue #70 — Macros System

### Root cause of the stuck PR
The captured test output `/bin/sh: 13: source: not found` indicates a test setup or fixture script is being executed under `/bin/sh` (dash on Debian/Ubuntu CI images) but uses the bash-only `source` builtin. The macro system itself does not need shell scripts; the failure is environmental and must be fixed before the suite can report. Additionally, after unblocking the shell, the implementation must conform to the existing plan and repo conventions. The plan below supersedes prior attempts.

### Step 1 — Diagnose and fix the shell-source failure (do this first)
1. Locate the failing fixture/setup script (likely a `conftest.sh`, `setup.sh`, or a shell snippet invoked from a pytest fixture in `backend/tests/`).
2. Add a proper shebang `#!/usr/bin/env bash` at the top of that file (or change the invocation to `bash <file>`).
3. Replace any `source <file>` calls with the POSIX-compatible `. <file>` form to keep the script portable.
4. Make the file executable (`chmod +x`) if it is invoked directly.
5. Re-run only the previously-failing fixture path locally to confirm the `source: not found` error is gone before doing anything else.

### Step 2 — Backend: parser + executor + interface (per existing plan, minimal diff)
1. Create `backend/macros/__init__.py`.
2. `backend/macros/parser.py`: implement `split_blocks(source) -> list[Block]` using a small tokenizer that tracks single/double quote state and brace depth so f-string braces like `{x_pos}` are not mis-parsed. Raise `MacroParseError(line_no, message)` on unbalanced braces. Output blocks are typed: `GCODE` or `PYTHON`.
3. `backend/macros/cnc_interface.py`: implement `CNCInterface` that wraps the existing `backend/hardware/connection.py` access path (never import `linuxcnc` directly). Methods: `emit(gcode)`, `log(message)`, `get_pos()`. `emit` routes through the existing command entry point so the 500 ms jog watchdog and mock fallback remain intact.
4. `backend/macros/executor.py`: implement `execute(source, params=None) -> MacroResult`. Walk blocks; for `GCODE` blocks call `cnc.emit(line)` line by line (strip empty/blank-only lines); for `PYTHON` blocks `exec(code, globals_dict)` where `globals_dict = {"cnc": CNCInterface(), "math": math, "__builtins__": __builtins__}`. Capture `cnc.log` calls into a `MacroResult.log_lines` list. Use module-level `logger = logging.getLogger(__name__)` — no `print`.
5. Add unit tests in `backend/tests/macros/` covering: simple G-code passthrough, Python block with `cnc.emit`, f-string brace handling, unbalanced-brace error, comment-only file.

### Step 3 — Backend: CRUD router
1. `backend/routers/macros.py` with `APIRouter(prefix="/api/macros", tags=["macros"])`. Endpoints:
   - `GET /` → list macros (name, size, mtime, parsed `; @description` header).
   - `GET /{name}` → raw source.
   - `PUT /{name}` → save (Pydantic `MacroSource` body, validate non-empty, reject `..`, `/`, NUL).
   - `DELETE /{name}` → delete (404 if missing).
   - `POST /{name}/run` → execute, return emitted lines + captured log.
2. Storage directory `backend/macros_store/*.macro`; resolve paths and assert `os.path.commonpath([store_dir, resolved]) == store_dir` to prevent traversal. Create dir at startup if absent.
3. Every endpoint declares `summary` and `description` metadata.
4. Register the router in `backend/main.py`.

### Step 4 — Frontend: Pinia store
1. `frontend/src/stores/macros.js` using Pinia setup style consistent with other stores. State: `items`, `current`, `log`. Actions: `fetchList`, `fetchOne`, `save`, `remove`, `run`. HTTP via the existing `/api` Vite proxy; on error, surface a user-readable message.

### Step 5 — Frontend: dashboard widget
1. `frontend/src/components/MacroGrid.vue` — `<script setup>`, 2-space indent, double quotes, semicolons, Tailwind v4 responsive grid (e.g., `grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3`). Click → `runMacro(name)`; success/failure toast using the existing toast utility if present, otherwise a transient inline status.
2. Mount `<MacroGrid />` in the existing dashboard view alongside other widgets.

### Step 6 — Frontend: editor view
1. `frontend/src/views/MacroEditor.vue` — three-pane layout: sidebar list (left), code editor (center), log/output panel (bottom). Use whichever code editor is already in `frontend/package.json` (Monaco or CodeMirror) — do not add a new heavy dependency unless required. If neither is present, default to a lightweight `<textarea>`-based editor for v1 and note the upgrade as follow-up.
2. Actions: Save, Run, Delete (with `confirm()` guard). Bind bottom panel to `store.log`.
3. Clean up editor instance, timers, and any workers on `onUnmounted`.
4. Register route `/macros` in `frontend/src/router/index.js`.

### Step 7 — Verify (do not run tests yourself)
1. Confirm the shell-source fix in Step 1 is the only environment change needed.
2. Ensure new files match repo conventions: backend uses 4-space indent, PEP 8, type hints, Pydantic bodies, `logging.getLogger(__name__)`; frontend uses Composition API `<script setup>`, 2-space indent, double quotes, semicolons, Tailwind v4 utilities, Pinia `storeToRefs` when destructuring.
3. Hand off to orchestrator for commit, test, push, PR. Do not run tests, push, or open the PR.

### Open items flagged for the human (do not silently decide)
- Confirm macro storage location: `backend/macros_store/` (gitignored or volume-mounted? — matches the issue's "predefined subroutines" framing).
- Confirm which code editor (Monaco vs CodeMirror) is already a frontend dependency; reuse it.
- Confirm module-system placement per `.agent/contracts/` and `MODULE_SYSTEM_ROADMAP.md` — likely a new `macros` module.
- Confirm whether the optional parameter modal (`; @param name default` header) is v1 scope or deferred.
- Issue waives sandboxing; add a docstring note in `parser.py` and `executor.py` stating that Python blocks execute with full privileges.

### Files expected to change
- New: `backend/macros/__init__.py`, `parser.py`, `cnc_interface.py`, `executor.py`; `backend/routers/macros.py`; `backend/tests/macros/test_parser.py`, `test_executor.py`; `frontend/src/stores/macros.js`; `frontend/src/components/MacroGrid.vue`; `frontend/src/views/MacroEditor.vue`.
- Modified: `backend/main.py` (router include); `frontend/src/router/index.js` (new route); dashboard view (mount widget); the shell fixture that caused `source: not found`.

## Research notes



## Notes per attempt

--- Attempt 1 ---

--- Attempt 2 ---

--- Attempt 3 ---

## Last test output (last 100 lines)

```
+ export CI=true
+ CI=true
+ '[' '!' -f .venv/bin/activate ']'
+ . .venv/bin/activate
++ deactivate nondestructive
++ '[' -n '' ']'
++ '[' -n '' ']'
++ hash -r
++ '[' -n '' ']'
++ unset VIRTUAL_ENV
++ unset VIRTUAL_ENV_PROMPT
++ '[' '!' nondestructive = nondestructive ']'
++ '[' linux-gnu = cygwin ']'
++ '[' linux-gnu = msys ']'
++ export VIRTUAL_ENV=/app/workspaces/q4yz/LinuxCNC_UI/.venv
++ VIRTUAL_ENV=/app/workspaces/q4yz/LinuxCNC_UI/.venv
++ _OLD_VIRTUAL_PATH=/root/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
++ PATH=/app/workspaces/q4yz/LinuxCNC_UI/.venv/bin:/root/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
++ export PATH
++ '[' -n '' ']'
++ '[' -z '' ']'
++ _OLD_VIRTUAL_PS1=
++ PS1='(.venv) '
++ export PS1
++ VIRTUAL_ENV_PROMPT='(.venv) '
++ export VIRTUAL_ENV_PROMPT
++ hash -r
+ '[' '!' -d frontend/node_modules ']'
+ npm --prefix frontend ci --no-audit --prefer-offline
npm error code EUSAGE
npm error
npm error `npm ci` can only install packages when your package.json and package-lock.json or npm-shrinkwrap.json are in sync. Please update your lock file with `npm install` before continuing.
npm error
npm error Missing: @emnapi/runtime@1.11.3 from lock file
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
npm error A complete log of this run can be found in: /root/.npm/_logs/2026-08-05T15_53_23_501Z-debug-0.log
```
