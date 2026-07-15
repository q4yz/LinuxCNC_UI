### Resolution Summary
Adds an asynchronous `EventBus` in `backend/core/event_bus.py` so backend modules (e.g. Temperature, VFD, Spindle) can communicate through topics without importing one another directly, with state-topic deduplication acting as a rate-limit to prevent high-frequency publishers from flooding the bus.

### Files Modified
- `backend/core/event_bus.py` (new): `EventBus` class with `subscribe(topic, callback)`, `unsubscribe(topic, callback)`, async `publish(topic, payload)`, `clear_cache()`, and a `_safe_invoke` wrapper. A module-level `bus` singleton is exposed for shared use.

### Architectural Decisions
- **Location**: Placed under `backend/core/` per the repository agent guide, which reserves `core/` for shared models and configuration-style plumbing; this matches how `config_manager.py` and `models.py` are organised.
- **Async fan-out**: Subscribers are dispatched concurrently via `asyncio.gather`, preserving the FastAPI async lifecycle required by `.agent/AGENT.md`.
- **Fail-safe delivery**: `_safe_invoke` wraps each callback so a single misbehaving subscriber logs an error but never tears down the bus or skips sibling subscribers — matching the issue's "fire and forget" intent.
- **Rate-limiting via state caching**: Topics prefixed with `state.` are deduplicated by comparing the incoming payload against the last published value. This addresses the issue's "rate-limiting or state-caching" requirement without imposing a fixed timer that would block the event loop. Non-state topics pass through unchanged so imperative commands (e.g. `vfd.set_freq`) are always delivered.
- **Logging**: Uses the project's `logging` style (module-level `logger = logging.getLogger(__name__)`) consistent with `backend/hardware/connection.py`.
- **Naming / style**: 4-space indentation, PEP 8 naming, type hints on public signatures — matches `backend/core/models.py` and `backend/hardware/connection.py`.
- **Singleton**: A module-level `bus = EventBus()` instance is exported so callers do `from core.event_bus import bus`, mirroring the issue's reference snippet.
- **Optional extras**: Added `unsubscribe()` and `clear_cache()` as small, focused helpers so consumers can tear down listeners cleanly during FastAPI shutdown or unit tests. These are non-breaking additions over the issue's example.

### Testing Verification
- [x] Ran local test suite / build checks
  - `python3 -m compileall -q backend` → passes (no syntax errors anywhere in `backend/`, including the new module).
  - Functional sanity script run from both the repo root and from `backend/`:
    - `state.temp = 60.0` delivered, second identical payload deduplicated, then `61.5` delivered.
    - Non-state topic `vfd.set_freq = 1200` delivered.
    - A subscriber that raises `RuntimeError` does not block the other subscriber on the same `alert` topic; the error is logged by `_safe_invoke`.
    - `unsubscribe()` removes the callback correctly.
- [ ] Frontend `npm --prefix frontend run build` was attempted but fails on **pre-existing** missing files (`frontend/generated/api/services/ConfigurationService`, `SystemService`, etc.) that are unrelated to this PR — `git status` shows only `event_bus.py` (and the local `.venv/`) added on this branch, and the missing generated files exist on `main` as well. This issue does not touch any frontend code, so the frontend build is out of scope here.