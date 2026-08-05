# AI STUCK - Issue #68

The automated agent was unable to make the test suite pass after 3 attempts. The branch below contains the most recent attempt and the captured failure logs.

## Issue

title:	add macro support
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
number:	68
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

Backend Python snippet for the executor
class CNCInterface:
def emit(self, gcode_str):
print(f"[TO LINUXCNC] {gcode_str}")
# In production: linuxcnc.command(gcode_str)

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

## Macro Support Implementation Plan (Issue #68)

### 1. Backend – Parser, Executor & Storage

**1.1 Add Pydantic models (`backend/core/macro_models.py`)**
- `MacroMeta`: `name`, `filename`, `description`, `params: list[MacroParam]`, `updated_at`.
- `MacroParam`: `name`, `default`, `type` (`str|int|float|bool`).
- `MacroContent`: `filename`, `body` (string).
- `MacroExecuteRequest`: `filename`, `params: dict`.
- Use 4-space indent, PEP 8, type hints.

**1.2 Macro storage location**
- Define `MACROS_DIR` in `backend/core/config.py` (defaults to `<repo>/macros/`, overridable via env). Ensure directory is created at startup (FastAPI lifespan).
- All file I/O funnels through a small helper that resolves filenames safely (`os.path.commonpath([MACROS_DIR, resolved]) == MACROS_DIR`) to prevent path traversal.

**1.3 Hybrid parser (`backend/services/macro_service.py`)**
- Single function `parse_and_execute(body: str, params: dict) -> list[str]` returning the ordered G-code lines to send to LinuxCNC.
- Algorithm:
  1. Tokenize by scanning for the first balanced `{` ... `}` block (handle nested braces via a simple depth counter).
  2. For text outside braces: append each non-blank line to the output G-code list verbatim.
  3. For Python inside braces: build a `macro_globals` dict containing `cnc` (the injected interface), `math` (`import math`), and a `params` dict. Call `exec(python_src, macro_globals)`.
  4. `CNCInterface` (`backend/services/macro_service.py` – local class) implements:
     - `emit(gcode: str)` – collects/prints lines and ultimately forwards to `backend/hardware/connection.py` async command queue.
     - `log(msg)` – uses module `logging`.
     - `get_pos()` – awaits the existing hardware connection position helper.
  5. Inside the Python block, `cnc.emit(...)` appends to the same G-code list so execution order matches source order.
- Raise `MacroParseError` (custom) on unbalanced braces or Python `SyntaxError`/`NameError` – the router translates this into HTTP 422 with an actionable message.

**1.4 Macro service – CRUD + execute**
- `list_macros()` → returns metadata for every `*.macro` file in `MACROS_DIR` (filename stem used as display name).
- `read_macro(filename)` / `write_macro(filename, body)` / `delete_macro(filename)`.
- `execute_macro(filename, params)` → parse, run, and feed the resulting G-code lines through the existing async LinuxCNC command path used by the current job runner (reuse whatever helper currently sends MDI / program lines – avoid touching `linuxcnc` directly so `linuxcnc_mock.py` still works).
- All file operations and `exec()` run via `asyncio.to_thread` so the FastAPI event loop is never blocked.

**1.5 Router (`backend/routers/macros.py`)**
- Prefix `/api/macros`, `tags=["macros"]`.
- Endpoints with `summary` + `description`:
  - `GET  /` → list
  - `GET  /{filename}` → body
  - `PUT  /{filename}` → save (validates filename, rejects traversal)
  - `DELETE /{filename}` → delete
  - `POST /{filename}/execute` → run with params
- Register the router in the existing router registration helper (where `main.py` currently mounts routers – do **not** add endpoints to `main.py`).

### 2. Frontend – Dashboard Grid + Editor View

**2.1 API service (`frontend/src/services/macros.js`)**
- Thin wrappers around `fetch` using the existing `apiBase`/Vite `/api` proxy:
  `list`, `get`, `save`, `remove`, `run`.
- All calls return Promises; errors surface a toast via the existing notification pattern (check how other services report errors and reuse it).

**2.2 Pinia store (`frontend/src/stores/macros.js`)**
- State: `macros: []`, `activeFilename`, `dirty`, `lastRunLog: string[]`.
- Actions: `fetchList`, `load`, `save`, `remove`, `run`.
- Uses Composition style (`defineStore('macros', () => { ... })`) to match the existing stores.
- Cross-store communication (e.g., starting a job requires the connection store) is done by lazily instantiating the other store inside the action per the global rule on circular init.

**2.3 Dashboard component (`frontend/src/components/MacroGrid.vue`)**
- `<script setup>`, 2-space indent, double quotes, semicolons.
- Reads `macros` via `storeToRefs`.
- Renders a responsive Tailwind v4 grid (`grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3`).
- Each macro is a button calling `store.run(name, params)`. Disable while running.
- V2 modal stub: if `macro.params.length > 0`, open a small inline dialog with labeled inputs and `Run` button. Keep it lightweight (no new dep) unless a modal pattern already exists.
- On execution, push output lines into a toast/log area that already exists for MDI/console.

**2.4 Macro Editor view (`frontend/src/views/MacroEditorView.vue`)**
- Layout: left sidebar (file list of macros – reuses store list), center editor, bottom console panel.
- Editor: pick the code-editor library already used in the project (research already gathered – if neither Monaco nor CodeMirror is installed, prefer **CodeMirror 6** because it is lighter and integrates with Vite without extra worker config; install only one). Wrap in a small `MacroEditor.vue` component that emits `update:modelValue`.
- Top action bar: `Save` (PUT), `Run` (POST execute with current param inputs), `Delete` (DELETE + confirm dialog using existing confirm pattern).
- Console panel: subscribe to `lastRunLog` from the store; render lines in a scrollable `<pre>` with `text-xs font-mono`.
- On unmount: dispose the editor instance and clear any timers/sockets per the global rule.

**2.5 Router integration**
- Add `/macros` (dashboard tiles, can also be embedded on the main dashboard if `App.vue` already has a slot) and `/macros/editor` (full IDE view) in the existing Vue router.
- Add a navigation entry consistent with the existing menu style.

**2.6 G-code constants (`frontend/src/config/gcodes.js`)**
- Add `MACRO_FILE_EXT = ".macro"` and helper `macroButtonLabel(meta)` if useful. No G-code strings should leak into components/stores.

### 3. Wiring, Logging, Safety

- `backend/services/macro_service.py` uses `logging.getLogger(__name__)` for `cnc.log` and parser diagnostics (no `print`).
- The executor routes G-code through `backend/hardware/connection.py`; do not import `linuxcnc` directly so `linuxcnc_mock.py` keeps working in dev.
- File-path validation rejects `..`, absolute paths, and non-`*.macro` extensions.
- The macro editor must not bypass the existing emergency-stop / jog-watchdog / connection-state checks: disable `Run` when the store reports the machine is not in a ready state (mirror the logic used by the MDI/Job runner).
- Continuous-jog watchdog and keepalive cadence remain untouched.

### 4. Tests / Validation
- Run every command listed in `.agent/TEST.md` before handoff.
- Manual smoke: list macros → run the included `probe_grid.macro` example (ship it under `macros/` for demo) → confirm G-code lines appear in the existing LinuxCNC command console.

### Files touched (expected)
- New: `backend/core/macro_models.py`, `backend/routers/macros.py`, `backend/services/macro_service.py`, `frontend/src/stores/macros.js`, `frontend/src/services/macros.js`, `frontend/src/components/MacroGrid.vue`, `frontend/src/components/MacroEditor.vue`, `frontend/src/views/MacroEditorView.vue`, `macros/probe_grid.macro` (demo).
- Modified: `backend/core/config.py` (add `MACROS_DIR`), router registration helper (mount new router), Vue router config, `frontend/src/config/gcodes.js`, `frontend/src/App.vue` or dashboard view (embed grid).
- Untouched: `backend/main.py`, jog/keepalive code, `backend/hardware/connection.py` (only consumed, not modified).

This is the smallest change that satisfies the acceptance criteria while honoring the global rules (monorepo layout, async safety, hardware abstraction, no direct `linuxcnc` import, Tailwind v4 utilities, Pinia patterns, editor/Three.js cleanup).

## Research notes

--- Research pass ---
<think>
The user is asking me to act as a Research agent supporting the Architect for implementing macro support (Issue #68) in this monorepo. I need to gather context about the repository to inform implementation decisions. Let me start by exploring the repository structure to understand the existing patterns.

Let me plan my research:
1. Understand the overall repo structure
2. Look at backend conventions (routers, services, hardware connection)
3. Look at frontend conventions (stores, components, views)
4. Check existing G-code command issuance patterns
5. Check file persistence patterns
6. Check editor libraries used (Monaco vs CodeMirror)
7. Check router registration helper
8. Check`.agent/TEST.md` for validation commands

Let me start exploring.
</think>

I'll research the repository structure and existing patterns to inform the macro support implementation. Let me explore systematically.]<]minimax[>[<tool_call>
<tool_code>
<invoke name="run_command">
<parameters>
<command>find . -type f -name '*.py' -o -name '*.vue' -o -name '*.js' -o -name '*.json' -o -name '*.md' -o -name '*.toml' -o -name '*.yml' -o -name '*.yaml' -o -name '*.txt' 2>/dev/null | grep -v node_modules | grep -v __pycache__ | grep -v '.git/' | head -150</command>
<cwd>.</cwd>
</invoke>
<invoke name="run_command">
<parameters>
<command>ls -la</command>
<cwd>.</cwd>
</invoke>
</tool_code>

## Notes per attempt

--- Attempt 1 ---

--- Attempt 2 ---

--- Attempt 3 ---
<think>
Let me look at more of the frontend code structure to understand the pattern used and then checkthe backend more carefully.
</think>

## Last test output (last 100 lines)

```
/bin/sh: 3: source: not found
```
