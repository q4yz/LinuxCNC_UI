# AI STUCK - Issue #72

The automated agent was unable to make the test suite pass after 3 attempts. The branch below contains the most recent attempt and the captured failure logs.

## Issue

title:	add Macros
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
number:	72
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

## Implementation Plan: Macros Feature (Issue #72)

This plan adds a hybrid Python/G-code macro system: a backend parser/executor with file-backed storage, a dashboard grid for one-click execution, and a dedicated Macro Editor view. It follows the existing backend FastAPI conventions (router under `backend/routers/`, Pydantic schemas, LinuxCNC access via `backend/hardware/connection.py`) and frontend Vue 3 conventions (Pinia store, Composition API, Tailwind utilities, `/api`+`/ws` proxies).

### Step 1 — Backend: macro module skeleton
Create `backend/macros/` with:
- `__init__.py`
- `parser.py` — hybrid G-code/Python tokenizer. Splits a macro string into ordered segments: `(gcode: str) | (python: str)`. The rule: text inside `{ ... }` is Python, everything else is raw G-code sent verbatim to LinuxCNC. Handle escaped braces `\{` `\}` and nested braces inside strings/comments so the tokenizer doesn't split on them.
- `executor.py` — `MacroExecutor` that walks segments, emits G-code through the injected connection, and `exec()`s Python blocks with a controlled `globals` dict containing a `CNCInterface` (methods `emit(gcode)`, `log(message)`, `get_pos()`, plus `math`). Captures `cnc.log()` output into an in-memory buffer and pushes it through a callback for WebSocket streaming.
- `storage.py` — file-based store for `.macro` files. Configurable root directory (default `data/macros/`), with helpers `list()`, `read(name)`, `write(name, content)`, `delete(name)`. Validates filenames against a safe regex to prevent path traversal (do not weaken filesystem safeguards).
- `cnc_interface.py` — `CNCInterface` class per the issue's mock spec. In production mode, `emit()` forwards to `linuxcnc.command()` via `backend/hardware/connection.py`; `log()` writes through the standard `logging` module and the executor's stream callback.

### Step 2 — Backend: Pydantic schemas
Create `backend/macros/schemas.py` (or inline in router if small):
- `MacroSummary` (name, updated_at, size)
- `MacroDetail` (name, content, updated_at)
- `MacroCreate` / `MacroUpdate` (name, content)
- `MacroExecuteRequest` (optional `parameters: dict[str, Any]` for V2 modal support)
- `MacroExecuteResponse` (job_id, status)

### Step 3 — Backend: API router
Create `backend/routers/macros.py` with prefix `/api/macros`, `tags=["macros"]`, full `summary`/`description` metadata:
- `GET /` → list macros (summary + filenames)
- `GET /{name}` → fetch content
- `POST /` → create (returns 409 if exists)
- `PUT /{name}` → update
- `DELETE /{name}` → remove
- `POST /{name}/execute` → run via executor; returns job id, streams logs via WebSocket

Register the router in `backend/main.py`. Keep endpoints `async def` (I/O-bound file + WS dispatch).

### Step 4 — Backend: WebSocket log streaming
Add a WebSocket endpoint (likely `backend/routers/ws.py` or a new `backend/routers/macro_ws.py`) at `/ws/macros/{job_id}` that joins the executor's log stream callback for a given job, forwarding each `cnc.log()` line to the client. Clean up the subscription on disconnect. Preserve existing jog watchdog / emergency-stop semantics — macro execution must respect the same active-state checks as the jog endpoints.

### Step 5 — Backend: safety + lifecycle
- Preserve the 500 ms jog watchdog semantics: if a macro is running, abort it on E-stop / disconnect (mirror existing jog behavior in `connection.py`).
- Add a per-job timeout and a max-recursion guard for `exec()`.
- Module-level logger pattern (`logger = logging.getLogger(__name__)`); no `print()`.

### Step 6 — Frontend: Pinia store
Create `frontend/src/stores/macros.js`:
- State: `macros`, `activeMacro`, `editorContent`, `runLogs`, `isRunning`, `currentJobId`.
- Actions: `fetchList()`, `fetchOne(name)`, `save(name, content)`, `remove(name)`, `run(name, params?)`.
- Use `storeToRefs()` at call sites. Hit `/api/macros` via the existing Vite proxy.

### Step 7 — Frontend: WebSocket composable
Create `frontend/src/composables/useMacroSocket.js` (or integrate into the store): connects to `/ws/macros/{jobId}`, pushes incoming log lines into the store's `runLogs`, closes on `onUnmounted` per project conventions.

### Step 8 — Frontend: Dashboard macro grid component
Create `frontend/src/components/MacroGrid.vue`:
- Fetches macro list on mount, renders a responsive Tailwind grid of buttons (wrap-around, large hit targets for touchscreen).
- Click → calls `store.run(name)`, opens a small toast/log drawer showing streaming output.
- Place it on the main dashboard view (`frontend/src/views/Dashboard.vue` or equivalent).
- Slot for V2 parameter modal (stub the prop now, no behavior required for V1).

### Step 9 — Frontend: Macro Editor view
Create `frontend/src/views/MacroEditor.vue`:
- Left sidebar: file list (from store), click to load into editor.
- Center: code editor — use **CodeMirror 6** (lighter than Monaco, fits the existing bundle profile; pick Monaco only if already a dependency). Configure G-code syntax highlighting via a custom mode, and a Python overlay for `{ ... }` blocks (e.g., via `overlay`). Lazy-import the editor module so it doesn't bloat the initial bundle.
- Bottom: console panel bound to `store.runLogs` (auto-scroll, clear button).
- Action bar: Save (PUT), Run (POST execute), Delete (DELETE + confirm). All wired through the store.
- 2-space indent, double quotes, semicolons, Tailwind utilities, `<script setup>`.
- Clean up editor instance, WebSocket, and timers in `onUnmounted`.

### Step 10 — Frontend: routing
Wire `/macros` (editor) and the dashboard slot in `frontend/src/router/*` (or wherever the route table lives). Add a nav entry consistent with existing dashboard items.

### Step 11 — Verification hooks (no test runs by agent)
Confirm `.agent/TEST.md` and existing contract tests under `.agent/contracts/` cover new endpoints and that the orchestrator's test pipeline picks up the new router. Add a contract entry under `.agent/contracts/macros.md` describing: storage path, parser contract (segment shape), executor globals, WS message shape (`{type: 'log'|'emit'|'done'|'error', payload}`).

### Out of scope (explicit)
- V2 parameter modal UI (placeholder only).
- Sandboxing of Python blocks (issue explicitly says full privileges).
- Migration of existing G-code programs into `.macro` files.

### Follow-up for human
- Decide macro storage root (config key vs. default `data/macros/`) and ensure the volume is persisted in deployment.
- Confirm CodeMirror vs Monaco if there is a preference; defaulting to CodeMirror 6 for bundle size.
- Review WebSocket auth model (currently matches existing `/ws` proxy behavior).


## Research notes



## Notes per attempt

--- Attempt 1 ---
<think>
**Surveying existing editor patterns and configuration workflows**
</think>

**

I have enough context now. Let me look at a few more components to understand the editor setup and CodeMirror integration.<tool_call>
]<]minimax[>[<invoke name="read_file">]<]minimax[>[<path>frontend/src/components/Editor.vue]<]minimax[>[</path>]<]minimax[>[</invoke>
]<]minimax[>[<invoke name="read_file">]<]minimax[>[<path>frontend/src/views/EditorView.vue]<]minimax[>[</path>]<]minimax[>[</invoke>
]<]minimax[>[<invoke name="read_file">]<]minimax[>[<path>frontend/src/views/SettingsView.vue]<]minimax[>[</path>]<]minimax[>[</invoke>
]<]minimax[>[<invoke name="read_file">]<]minimax[>[<path>frontend/src/components/ConsolePanel.vue]<]minimax[>[</path>]<]minimax[>[</invoke>
]<]minimax[>[<invoke name="read_file">]<]minimax[>[<path>frontend/src/components/ActivePrintWidget.vue]<]minimax[>[</path>]<]minimax[>[</invoke>
]<]minimax[>[<invoke name="read_file">]<]minimax[>[<path>frontend/vite.config.js]<]minimax[>[</path>]<]minimax[>[</invoke>
]<]minimax[>[</tool_call>

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
npm error A complete log of this run can be found in: /root/.npm/_logs/2026-08-05T22_00_31_874Z-debug-0.log
```
