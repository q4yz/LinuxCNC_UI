### Resolution Summary
Implemented the issue #63 print-control surface: four new `POST` endpoints on the machine module (`/print`, `/pause`, `/resume`, `/stop`) plus a thread-safe program-execution simulation in `linuxcnc_mock.py` that drives the existing `current_line` / `interp_state` telemetry so the frontend `printProgress` getter and `SystemState` facade keep working in the Windows dev environment.

### Files Modified
- `backend/modules/machine/router.py`: Added `PrintCommand` request model, `_require_machine_ready()` safety guard (polled `stat` rejects E-Stop / powered-off state with HTTP 400), and four new endpoints (`start_print`, `pause_print`, `resume_print`, `stop_print`) that call into the existing `execute_sync_cmd` / `linuxcnc.command()` layer.
- `backend/modules/machine/module.py`: Updated manifest description to mention G-code execution; merged router surface already includes the new endpoints via the `APIRouter` returned by `get_router()`.
- `backend/hardware/linuxcnc_mock.py`: Added `total_lines` field on `SharedMachineState`, exposed it on the `stat` snapshot, and replaced the previously stub `auto` / `program_open` / `abort` / `reset_interpreter` paths with a real single-threaded simulation (`_program_simulation_loop` + `_start_program_simulation_if_needed` + `_stop_program_simulation`) that advances `current_line` at ~10 Hz, honours `AUTO_PAUSE` / `AUTO_RESUME` and reverts to `INTERP_IDLE` on completion or `abort`.

### Architectural Decisions
- The four new endpoints live on the machine module (per the issue) and the existing `ProgramModule` (the `POST /run|stop|pause|resume` equivalents at `/api/v1/modules/program`) was left untouched. The new `POST /machine/print` always issues `program_open` + `AUTO_RUN` and the new `POST /machine/{pause,resume,stop}` are simple pass-throughs; the program module is unaffected.
- Safety is enforced via `_require_machine_ready()` which polls the stat object immediately before each call, so E-Stop or power transitions that happen mid-session are reflected on the very next request. The guard returns HTTP 400 with a human-readable `detail`.
- The mock's simulation thread is started/stopped on each `AUTO_RUN` / `AUTO_RESUME` and `AUTO_PAUSE` / `abort` transition respectively, and is *also* stopped/replaced when `program_open` or `reset_interpreter` is called — covering the legacy `load_program` flow and any direct command invocations.
- A pre-existing deadlock bug was discovered while wiring `AUTO_PAUSE` (calling `_stop_program_simulation` from inside a `with _machine_state.lock:` block). It has been fixed by hoisting that call out of the `with` block; the mock's lock is non-reentrant (`threading.Lock`), so the same trap is documented inline to prevent regressions.
- The `total_lines` default of 1000 mirrors the issue's recommended value; the simulation thread reaches the end and flips `interp_state` to `INTERP_IDLE` so the WebSocket telemetry loop reflects the transition without a manual abort.

### Testing Verification
- [x] `python3 -m compileall -q backend` — passes.
- [x] `python3 -m pytest backend/tests -q` — **178 passed** (pre-fix `main` branch via `git stash` also reports 178 passed; my changes do not regress the existing machine / program / temperature / registry suite).
- [x] `npm --prefix frontend run build` — passes (pre-existing chunk-size and dynamic-import warnings only, unrelated to this change).
- [x] `node --test frontend/tests/test-machine-facade.mjs` — 16/16 pass.
- [x] `node frontend/scripts/check-store-ids.mjs` — OK.
- [x] Manual `TestClient` smoke test: with the machine in `STATE_ESTOP_RESET` + `STATE_ON`, `POST /print` -> `200`, `POST /pause` -> `200` (interp_state flips to `INTERP_PAUSED`), `POST /resume` -> `200` (flips back to `INTERP_READING`, the simulation thread advances `current_line` to ~5 over 300 ms), `POST /stop` -> `200` (interp_state=`INTERP_IDLE`, current_line/total_lines reset, simulation thread joins cleanly). E-Stop state and `STATE_OFF` both return `400` from every endpoint; blank filenames return `400`. The simulation thread is reaped on every stop so no zombies linger.
