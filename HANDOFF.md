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

## Issue #70 — Macros System: Implementation Plan

### Overview
Add a hybrid G-code/Python macro subsystem: backend parses `.macro` files (G-code with `{ ... }` Python blocks), evaluates Python via `exec()` with an injected `cnc` mock interface, and feeds the resulting G-code through `backend/hardware/connection.py`. Frontend gets a Mainsail-style dashboard grid for one-click execution and a dedicated editor view with sidebar + code editor + log console.

### Backend

1. **New package `backend/macros/`**
   - `parser.py` — `split_blocks(source) -> list[Block]` separating G-code text from top-level `{ ... }` Python blocks. Must skip braces inside Python string literals (f-strings in the example contain `{x_pos}`). Recommend a small tokenizer that tracks quote state, rather than a naive regex. Raise `MacroParseError` on unclosed braces with line number.
   - `cnc_interface.py` — `CNCInterface` class wrapping `backend/hardware/connection.py` (never import `linuxcnc` directly). Methods: `emit(gcode)`, `log(message)`, `get_pos()`. `emit` calls the existing connection command path so jog-watchdog / mock compatibility is preserved.
   - `executor.py` — `execute(source, params=None) -> MacroResult`. Walks blocks: G-code blocks pass through to `cnc.emit`; Python blocks run via `exec(code, globals_dict)` where `globals_dict = {"cnc": CNCInterface(...), "math": math, ...}`. Captures `cnc.log()` output into the returned result. Log via `logging.getLogger(__name__)` — never `print`.

2. **New router `backend/routers/macros.py`** (prefix `/api/macros`, `tags=["macros"]`)
   - `GET /` — list macros (filename + size + optional `description` header parsed from `;` comments).
   - `GET /{name}` — return raw source for the editor.
   - `PUT /{name}` — save source; Pydantic body validates non-empty + allowed characters (reject `..`, `/`, NUL).
   - `DELETE /{name}` — remove file.
   - `POST /{name}/run` — execute and return emitted lines + captured log.
   - All endpoints carry `summary` and `description`. Use Pydantic schemas (inline is fine; small surface).
   - Storage path: `backend/macros_store/*.macro`, path-traversal-safe via `os.path.commonpath` check.

3. **Wiring**
   - Register the router in `backend/main.py`.
   - No changes to jog-watchdog or keepalive semantics.

### Frontend

1. **Pinia store `frontend/src/stores/macros.js`**
   - State: `macros`, `current`, `log`.
   - Actions: `fetchList`, `fetchOne`, `save`, `delete`, `run`. Uses the Vite `/api` proxy.

2. **Dashboard widget `frontend/src/components/MacroGrid.vue`**
   - `<script setup>` Composition API, Tailwind v4 responsive grid of buttons.
   - Click → `runMacro(name)`; success/failure toast.
   - V2 parameter modal: defer to follow-up unless trivially in scope; the macro format does not yet define a parameter manifest, so a clean extension point is to read a `; @param name default` header line and open a modal — flag for human confirmation before implementing.

3. **Editor view `frontend/src/views/MacroEditor.vue`**
   - Three-pane layout: sidebar list, code editor (Monaco or CodeMirror — pick whichever is already in `frontend/package.json`; do not add a new heavy dep unless necessary), bottom log/output panel bound to `store.log`.
   - Save / Run / Delete actions; confirm dialog on delete; clean up editor instance on `onUnmounted`.
   - Route `/macros` added to `frontend/src/router/index.js`.

4. **Dashboard integration**
   - Mount `MacroGrid` in the existing dashboard view.

### Implementation Order
1. Backend parser + `CNCInterface` + executor (testable via curl `POST /run`).
2. Backend CRUD endpoints + storage + router registration.
3. Pinia store + dashboard widget.
4. Editor view with code-editor integration.
5. Optional parameter-modal pass.

### Files Touched (approx.)
- New: `backend/macros/parser.py`, `backend/macros/executor.py`, `backend/macros/cnc_interface.py`, `backend/routers/macros.py`, `frontend/src/components/MacroGrid.vue`, `frontend/src/views/MacroEditor.vue`, `frontend/src/stores/macros.js`.
- Modified: `backend/main.py` (router include), `frontend/src/router/index.js`, dashboard view.

### Open Items for the Human / Implementer
- Confirm macro storage location and whether `backend/macros_store/` should be gitignored or volume-mounted.
- Confirm whether Monaco or CodeMirror is already a dependency; prefer reusing the existing one.
- Confirm module-system placement per `.agent/contracts/` and `MODULE_SYSTEM_ROADMAP.md` — this feature may be a new module or live under an existing one.
- Confirm whether the optional parameter-modal (`; @param` manifest) is in scope for v1 or deferred.
- The issue explicitly waives sandboxing; the parser/executor docstrings should still state this clearly so future maintainers do not assume isolation.

## Research notes



## Notes per attempt

--- Attempt 1 ---

--- Attempt 2 ---
<think>
Let me look at the EditorView and the FileManager to better understand conventions.
</think>

--- Attempt 3 ---

## Last test output (last 100 lines)

```
/bin/sh: 13: source: not found
```
