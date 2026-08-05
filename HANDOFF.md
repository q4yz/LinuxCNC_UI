# Fix for Issue #82

## Plan

## Macro Support — Plan for This Iteration

### Phase 1 — Focused Research (3 reads)
Read exactly these three files in a single forward pass to unblock the backend work:

1. **`frontend/src/router/index.js`** — confirm route registration pattern (lazy vs eager imports), `meta` shape (title, icon, etc.) and where to add the `/macros` route. *Note only; no frontend code this iteration.*
2. **`frontend/src/views/Dashboard.vue`** (plus one sibling if the grid lives elsewhere) — confirm the Tailwind grid utilities, card wrapper, and widget-slot pattern the new `MacroGrid` widget will plug into. *Note only.*
3. **`backend/hardware/connection.py`** — capture the exact public API of the `connection` singleton (e.g. `command()`, `state`, `position` getters, any async variants) so `CNCInterface` wraps it without duplicating behaviour and without importing `linuxcnc` directly. This is the *binding contract* for the executor.

Do not browse beyond these files. Do not read `package.json` (CodeMirror 6 already chosen).

### Phase 2 — Backend Foundation (the four files requested by the reviewer)

4. **`backend/macros/__init__.py`** — `MacroStore` class:
   - Resolves a configurable macro directory (default `backend/macros/`) at construction; allows override for tests.
   - Methods: `list() -> list[str]`, `read(name) -> str`, `write(name, body) -> None`, `delete(name) -> None`.
   - Filename sanitisation: allow only `[A-Za-z0-9_-]`, must end with `.macro`; reject `..`, absolute paths, anything else. This is the path-traversal guard.
   - Module-level `logger = logging.getLogger(__name__)`.

5. **`backend/macros/schemas.py`** — Pydantic models (4-space indent, type hints):
   - `MacroSummary(name: str, description: str = "")`.
   - `MacroContent(name: str, body: str)`.
   - `MacroRunRequest(parameters: dict[str, Any] | None = None)`.
   - `MacroRunResponse(run_id: str)`.
   - `MacroEvent` discriminated union: `{type: "log" | "gcode" | "error" | "done", payload}` — matches the WS streaming shape.

6. **`backend/macros/parser.py`** — `parse(body: str) -> list[Segment]`:
   - `Segment` is a tiny dataclass with `kind: Literal["gcode", "python"]` and `text: str`.
   - Brace-balanced scan (single-pass state machine, **not** regex) so `{ print("}") }` is handled correctly and unmatched `{` raises `MacroParseError`.
   - Pure function; no I/O; easy to unit-test.

7. **`backend/macros/executor.py`** — execution engine:
   - `CNCInterface` class wrapping `backend.hardware.connection.connection` (real). Reads the API captured in step 3 and delegates — no direct `linuxcnc` import.
   - `MockCNCInterface` for tests / no-hardware runs, with `emit`/`log`/`get_pos` matching the issue spec; logs to module logger via `logging` (not `print`).
   - `build_globals(cnc, params)` returns the injected context: `cnc`, `math` (the real module), `time`, `params`.
   - `run_macro(name, params=None)` async generator yielding `MacroEvent` dicts (`log` from `cnc.log`, `gcode` from `cnc.emit`, `error` on exception, `done` at end). G-code goes through `cnc.emit` so the jog watchdog / E-stop / mock-fallback semantics from `connection.py` are preserved unchanged.
   - Catches and surfaces exceptions from `exec()` as `error` events; never silently swallows.
   - Module-level logger.

### Stop Point
After steps 4–7 are drafted, **stop** and return the single-paragraph summary per the workflow rules. Do not start the router, the frontend, the seed macro, or the WS wiring in this iteration — the reviewer asked specifically for the foundation files plus a status report. The orchestrator will hand the next round (router + wiring + frontend + seed) as a follow-up.

### Conventions reaffirmed
- 4-space indent, PEP 8, type hints on public functions.
- `logging.getLogger(__name__)` in every new file; no `print`.
- All G-code leaves the system via `backend/hardware/connection.py` — never `linuxcnc` direct.
- Filename validation at the HTTP boundary (relevant once router is added; flagged now so it isn't forgotten).
- Smallest possible diff; no edits outside `backend/macros/` this iteration.

## Implementation notes

--- Attempt 1 ---
<think>
Both files written. Let me give my one-paragraph summary.

The plan was clear: draft the four foundation files in `backend/macros/`. Two of them (`__init__.py` and `parser.py`) already matched the plan well, so I left them alone. For `schemas.py` and `executor.py` I tightened them against the plan's spec — schemas added the `done` discriminator, switched `MacroSummary.description` to `str = ""`, and dropped the extra `status` field on `MacroRunResponse`; executor added `MockCNCInterface`, a `build_globals(cnc, params)` helper, a `drain_logs()` mechanism so `cnc.log(...)` calls surface as `log` events, a terminal `done` event, and removed the dead `del uuid` line. G-code still leaves the system through `backend.hardware.connection.connection.get_machine_cmd().mdi(...)`, preserving the watchdog / E-stop / mock-fallback semantics, and the executor still surfaces Python and emit exceptions as `error` events without swallowing them. Stopping at the plan's stop point: no router, no frontend, no seed macro, no WebSocket wiring this round — the orchestrator can hand thoseas the next iteration.
</think>

I tightened the two foundation files that drifted from the plan while leaving `__init__.py` (the `MacroStore` is already path-safe with the `[A-Za-z0-9_-]+\.macro` regex and `is_relative_to` guard) and `parser.py` (the brace-balanced scanner with `ast.parse` validation and `MacroParseError` already satisfies the spec) untouched. In `schemas.py` I added the missing `"done"` to `MacroEvent.type`'s `Literal`, switched `MacroSummary.description` from `str | None = None` to `str = ""` per the plan, and dropped the speculative `status` field from `MacroRunResponse` so the schema carries only `run_id`. In `executor.py` I removed the dead `import uuid` / `del uuid` pair, added `MockCNCInterface` (matching the issue's `emit`/`log`/`get_pos` surface but writing to the module logger so tests and hardware-less runs work), factored out `build_globals(cnc, params)` so the `cnc` / `math` / `time` / `params` context is the single source of truth, gave both interfaces a `drain_logs()` so `cnc.log(...)` calls from inside a macro actually surface as `log` `MacroEvent` rows (previously they only went to the persistent console logger), wrapped `cnc.emit` in a try/except so an MDI failure becomes an `error` event instead of crashing the generator, and appended a final `MacroEvent(type="done", ...)` so WS consumers have a deterministic stream terminator. G-code still flows through `backend.hardware.connection.connection.get_machine_cmd().mdi(...)` so the jog watchdog, E-stop, and mock-fallback semantics in `connection.py` are preserved unchanged, and all module-level diagnostics go through `logging.getLogger(__name__)` with no `print`. I am stopping at the plan's stop point — no router, frontend, seed macro, or WebSocket wiring in this round; those are the next iteration's job.

--- Attempt 2 ---
<think>
The fix is applied. I replaced both `yield from _drain_log_events(cnc)` statements with the equivalent `for event in _drain_log_events(cnc): yield event` pattern, which is the correct way to forward events from a sync iterable inside an async generator function. Everything else in the file is byte-for-byte identical to the previous version.

Now I need to output a single-paragraph summary with no tool calls, as required by the workflow.
</think>

The `SyntaxError` came from using `yield from` inside `async def run_macro`, which is illegal — `yield from` only exists for synchronous generators. I replaced both occurrences (after each G-code emit and after each Python block) with the equivalent `for event in _drain_log_events(cnc): yield event` form so the async generator can forward drained log events without changing any behaviour, semantics, or surrounding code. No other files were touched; the orchestrator can re-run `python -m compileall -q backend` to confirm `backend/macros/executor.py` now compiles cleanly and proceed with the remaining macro wiring.
