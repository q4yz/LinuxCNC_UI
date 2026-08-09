### Resolution Summary
The FastAPI backend now tolerates LinuxCNC being down at startup and at any other time during the process lifetime. A new `ConnectionState` enum (`READY` / `LINUXCNC_DISCONNECTED` / `UNKNOWN`) tracks the binding lifecycle, a background retry loop reconnects every 5 s, and the WebSocket telemetry payload surfaces the state to the frontend so the dashboard can show a "waiting for LinuxCNC" banner instead of locking up.

### Files Modified
- `backend/hardware/connection.py`: Added a thread-safe state machine (`ConnectionState`, `get_connection_state`, `add_state_listener`, `remove_state_listener`), a `_try_bind` helper that never raises (catches the bind/poll failure path), a `try_reconnect` API, and the `connection_retry_loop` coroutine. `execute_sync_cmd` now returns a 503 when the binding is offline, and the holders (`get_machine_stat` / `get_machine_cmd` / `get_machine_error`) return `None` instead of fake live objects while disconnected. The `Connection` wrapper exposes the new surface as object methods.
- `backend/hardware/__init__.py`: Re-exports the new helpers (`ConnectionState`, `get_connection_state`, `is_ready`, `try_reconnect`, listener add/remove, `connection`) so other modules can import them without reaching into the submodule.
- `backend/main.py`: The lifespan now logs the initial connection state at startup and schedules `connection_retry_loop` as a background asyncio task alongside the telemetry loop. The retry task is cancelled on shutdown.
- `backend/routers/websocket.py`: `get_current_state` returns an ESTOP-bias sentinel (no `None`/AttributeError) when the binding is disconnected, and now includes a `connection_state` field in every payload — both the `full_state` sent on connect and the delta broadcast every 100 ms. The telemetry loop and the `websocket_telemetry` handler both tolerate a `None` holder and a raising `poll()`.
- `backend/tests/test_connection_state.py`: New file with 15 tests covering the state machine, retry loop, listener bookkeeping, and the WebSocket payload.

### Architectural Decisions
- **State is read-only, holders are the source of truth.** The state machine is a small enum + listeners while the actual `stat` / `command` / `error_channel` objects remain the canonical binding. The retry loop is the only writer of those holders; the telemetry loop only reads. This avoids races between the retry loop and the live pollers.
- **503 on disconnected calls, not 500.** Routers that forward to `execute_sync_cmd` get an actionable error response. The frontend already maps HTTP 503 to a "service unavailable" toast via the OpenAPI client.
- **ESTOP-bias sentinel in the telemetry payload.** When the binding is disconnected, the payload reports `task_state=1` (ESTOP) and `estop=1` — the same values the WebSocket payload already uses when the machine module is not mounted. This means the dashboard never claims the machine is idle while we have no real data, satisfying the VISION.md principle "the UI never claims the machine is idle when we have no data."
- **5 s retry interval.** Short enough to feel responsive after LinuxCNC starts, long enough to avoid log spam on a misconfigured controller. The interval is a parameter on `connection_retry_loop` so tests can override it.
- **State-change logging on every transition.** The same `INFO`-level log line on every state change makes it easy to correlate "backend started" with "LinuxCNC came up" in operator logs.
- **The frontend was not changed.** The new `connection_state` field is additive and the existing dashboard already defaults to ESTOP. Wiring the frontend to render a "waiting for LinuxCNC" banner is a follow-up that can be done without touching the wire format.

### Testing Verification
- [x] Ran `python -m compileall -q backend` — clean.
- [x] Ran `python -m pytest backend/tests -v` — **332/332 pass** (15 new tests in `test_connection_state.py` plus all 317 pre-existing tests).
- [x] Ran `node --test "frontend/tests/**/*.mjs"` — 98/98 pass.
- [x] Ran `npm --prefix frontend run build` — succeeds.
- [x] Manually started the backend with `python -m uvicorn main:app` and confirmed the lifespan logs the new state-transition lines (`LinuxCNC connection state: UNKNOWN -> READY`, `LinuxCNC binding is READY on startup`, `LinuxCNC connection retry loop running (interval=5.0s)`).
- [x] Verified the WebSocket `/ws/telemetry` payload includes `connection_state` via a `TestClient` integration test and an out-of-band manual probe.

### Acceptance Criteria
- [x] Catch connection/initialization exceptions on FastAPI startup when attempting to bind to LinuxCNC. → `_try_bind` swallows any exception; the import-time initial bind is wrapped in the same helper.
- [x] Instead of crashing or locking up, set an internal state to `LINUXCNC_DISCONNECTED`. → `_set_state(ConnectionState.LINUXCNC_DISCONNECTED)` after a failed bind.
- [x] Implement a background polling loop or connection retry mechanism that periodically checks for LinuxCNC. → `connection_retry_loop`, started by the FastAPI lifespan, every 5 s. Each tick also re-probes a live `READY` binding so a LinuxCNC shutdown is detected.
- [x] When LinuxCNC starts, the backend must successfully connect and update its state to `READY` without requiring a manual restart of the FastAPI service. → The retry loop attempts `_try_bind` on every tick and updates the state to `READY` on success. Tests cover the disconnected → ready transition.
