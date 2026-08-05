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

## Issue #70 — Macros System: Revised Implementation Plan

### Context
A previous attempt left the test suite broken with `/bin/sh: 13: source: not found`. That is a shell-compatibility failure: something in the test path is invoking `/bin/sh` (POSIX) but the script uses `source` (bash builtin). The plan below resolves that root cause first, then implements the macros feature end-to-end against the issue's acceptance criteria.

### Step 1 — Diagnose & fix the shell failure (blocker)
1. Locate every shell script touched by tests: `find . -name '*.sh' -not -path './node_modules/*' -not -path './.git/*'` and any `subprocess.run` / `os.system` / `pytest` fixture that invokes a shell.
2. For each offending file: either change the shebang to `#!/usr/bin/env bash` and ensure the test runner invokes it via `bash`, or replace `source X` with the POSIX `. X` form. Pick the smallest change that matches the project's existing convention — if other test scripts already use `bash`, follow that; if everything else is POSIX, use `.`.
3. If the failure is inside `conftest.py` (e.g., a fixture that calls `subprocess.run(['sh', '-c', 'source ...'])`, or a helper script sourced via `subprocess`), rewrite the invocation to pass the script directly to `bash` or inline the export as a single `-c` argument with `&&`.
4. Re-run the targeted failing test locally via the test harness to confirm the shell error is gone before moving on.

### Step 2 — Backend: parser, interface, executor
1. Create `backend/macros/` package.
2. `backend/macros/parser.py` — `split_blocks(source) -> list[Block]`. Implement a small state-machine tokenizer that tracks `{}` nesting and string-literal quote state (handles `'`, `"`, f-string `{}` inside Python blocks). Top-level `{ ... }` segments are Python; everything else is G-code text. Raise `MacroParseError(line, message)` on unclosed braces. Use `logging.getLogger(__name__)`, never `print`.
3. `backend/macros/cnc_interface.py` — `CNCInterface` wrapping `backend/hardware/connection.py`'s command path (never import `linuxcnc` directly so the mock stays compatible). Methods: `emit(gcode)`, `log(message)` (captured into a per-run buffer), `get_pos()`.
4. `backend/macros/executor.py` — `execute(source, *, on_log=None) -> MacroResult`. Walks blocks; G-code blocks go to `cnc.emit`; Python blocks run via `exec(code, globals_dict)` with `globals_dict = {"cnc": CNCInterface(...), "math": math, "__builtins__": __builtins__}`. Log a clear docstring that sandboxing is intentionally waived per the issue.
5. Module-level `logger = logging.getLogger(__name__)` pattern in every new file.

### Step 3 — Backend: router + storage
1. `backend/macros/storage.py` — `MACROS_DIR = backend/macros_store/`. Path-traversal-safe helpers: `safe_path(name)` using `os.path.commonpath` against `MACROS_DIR`, reject `..`, `/`, NUL, non-`.macro` extensions.
2. `backend/routers/macros.py` — prefix `/api/macros`, `tags=["macros"]`, async where I/O-bound. Pydantic request/response models (inline is fine). Endpoints with `summary` + `description`:
   - `GET /` → list `{name, size, description}` where `description` is the first `;` comment.
   - `GET /{name}` → raw source.
   - `PUT /{name}` → save (validate non-empty + safe name).
   - `DELETE /{name}` → remove.
   - `POST /{name}/run` → execute, return `{emitted: [...], log: [...], ok: bool}`.
3. Wire into `backend/main.py` via `app.include_router(macros.router)`.
4. Add `backend/macros_store/` to `.gitignore`.

### Step 4 — Frontend: Pinia store
1. `frontend/src/stores/macros.js` — state `{ list, current, log, running }`, actions `fetchList`, `fetchOne`, `save`, `remove`, `run` using the Vite `/api` proxy. Use `storeToRefs` at consumer sites.

### Step 5 — Frontend: dashboard widget
1. `frontend/src/components/MacroGrid.vue` — `<script setup>`, Composition API, 2-space indent, double quotes, semicolons. Tailwind v4 responsive grid (`grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3`). Each button calls `store.run(name)` and toasts success/error. Skip the parameter-modal v2 path unless the human confirms it's in scope — leave a clean extension point keyed off an optional `; @param name default` header.
2. Mount `<MacroGrid />` in the existing dashboard view next to current widgets.

### Step 6 — Frontend: editor view
1. `frontend/src/views/MacroEditor.vue` — three-pane layout: left sidebar listing macros (binds to `store.list`), centre code editor, bottom log panel bound to `store.log`. Editor choice: inspect `frontend/package.json` for `monaco-editor` / `@codemirror/*`; reuse whichever is present. If neither is present and adding one is needed, prefer CodeMirror 6 (lighter, Vue-friendly) — flag for human confirmation before adding a new heavy dep.
2. Buttons: Save (`store.save`), Run (`store.run` on current selection), Delete (confirm dialog → `store.remove`). Dispose editor instance + any timers in `onUnmounted`.
3. Add route `/macros` in `frontend/src/router/index.js` with a sensible nav entry.

### Step 7 — Tests & verification
1. Backend unit tests for `parser.split_blocks`: covers plain G-code, single Python block, nested f-string braces inside a Python block, unclosed brace error, comment handling.
2. Backend integration test for `POST /api/macros/{name}/run` using the mock `CNCInterface` (no real `linuxcnc`).
3. Storage path-traversal test (rejects `../etc/passwd`, absolute paths, NUL).
4. Frontend: a smoke component test for `MacroGrid` rendering and a store action test mocking the API.
5. Confirm `/bin/sh` shell failure from attempt 1–3 is gone before declaring done.

### Files touched (expected)
- New: `backend/macros/{__init__.py,parser.py,executor.py,cnc_interface.py,storage.py}`, `backend/routers/macros.py`, `backend/macros_store/.gitkeep`, `frontend/src/stores/macros.js`, `frontend/src/components/MacroGrid.vue`, `frontend/src/views/MacroEditor.vue`, plus targeted tests.
- Modified: `backend/main.py`, `frontend/src/router/index.js`, the dashboard view file, `.gitignore`, and whichever shell script triggered the `source` failure.

### Open questions for the human before coding
- Which code editor dep (if any) is already in `frontend/package.json` — reuses that, otherwise confirm CodeMirror 6 is acceptable.
- Confirm `backend/macros_store/` as the storage location and that it should be gitignored.
- Confirm parameter-modal (`; @param` manifest) is deferred to v2.
- Confirm module placement per `.agent/contracts/` (new module vs. existing one).

## Research notes

--- Research pass ---
<think>
The user wants me to act as a Research agent supporting the Architect. I need to search for libraries and best practices to solve this issue. The issue is about implementing a Macros feature for a LinuxCNC web UI, inspired by Mainsail's macro panel. The feature needs:

1. **Backend**: Parser/executor for hybrid Python/G-code macros (PHP-style templating where `{ ... }` blocks are Python)
2. **Frontend Dashboard**: Macro execution grid (like Mainsail)
3. **Frontend Editor**: Dedicated macro editor view with file tree + code editor + console

The PLAN UNDER CONSIDERATION has already been worked out. My job as the Research agent is to gather any additional context needed — specifically I should:
- Verify library recommendations are widely used, production-ready, actively maintained
- Not recommend obscure packages
- Search for libraries and best practices

Let me start by exploring the repository to understand the current state, then research libraries for:
1. Code editor for the frontend (Monaco vs CodeMirror — the plan says check if either is already installed, otherwise fallback to textarea)
2. Backend Python parser/executor patterns
3. Best practices for the hybrid G-code/Python parsing

Let me look at:
- `frontend/package.json` to see what's already installed (check for Monaco, CodeMirror)
- `backend/` structure
- `.agent/TEST.md` and any conftest that might be the source of the shell error
- `backend/hardware/connection.py` to understand the mock
- `MODULE_SYSTEM_ROADMAP.md` and `.agent/contracts/`

Let me dothis efficiently — focused lookups, not aimless browsing.
</think>

I'll research the context needed to support the Architect's plan for Issue #70. Let me gather information about the current state of the repo and verify library availability.]<]minimax[>[
invoke
invoke
invoke
invoke
invoke

## Notes per attempt

--- Attempt 1 ---

--- Attempt 2 ---

--- Attempt 3 ---

## Last test output (last 100 lines)

```
/app/workspaces/q4yz/LinuxCNC_UI/.agent_tmp_test.sh: line 13: .venv/bin/activate: No such file or directory
```
