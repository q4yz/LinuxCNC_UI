# `modules/machine/` — Machine module

Axis, state, jog, MDI, home, and set-position endpoints migrated from
`backend/routers/machine.py` + `backend/routers/jog.py` into the
registry-driven module system (issue #38).

## Layout

```
modules/machine/
├── __init__.py        # re-exports setup() so the registry can find it
├── module.py          # MachineModule(PluggableModule) — lifecycle hooks
├── router.py          # /state /mode /home /mdi endpoints
├── jog.py             # /jog /jog/keepalive /jog/stop + module-private _active_jogs
├── jog_watchdog.py    # 500 ms keep-alive safety watchdog
├── settings.py        # Pydantic MachineSettings (watchdog timeout + defaults)
└── README.md          # this file
```

The companion `modules/program/` package hosts the program-lifecycle
endpoints (run / stop / pause / resume / parse) so that
`routers/machine.py` could be deleted in issue #38. Program's UI lands
in Phase 3 — the package today exposes the HTTP surface only.

## Endpoints

Mounted by `ModuleRegistry._mount` at `GET/POST /api/v1/modules/machine/...`
with OpenAPI tag `modules:machine`.

| Method | Path                                       | Description |
|--------|--------------------------------------------|-------------|
| POST   | `/api/v1/modules/machine/state`            | Set machine E-Stop / Power state. |
| POST   | `/api/v1/modules/machine/mode`             | Set task mode (manual / auto / mdi). |
| POST   | `/api/v1/modules/machine/home`             | Home a single axis or all axes (`axis=-1`). |
| POST   | `/api/v1/modules/machine/mdi`              | Execute a single MDI command. |
| POST   | `/api/v1/modules/machine/jog`              | Start, step, or stop a jog. |
| POST   | `/api/v1/modules/machine/jog/keepalive`    | Refresh the watchdog timer. |
| POST   | `/api/v1/modules/machine/jog/stop`         | Explicitly stop a continuous jog. |
| GET    | `/api/v1/modules/machine/settings`         | Merged settings payload (defaults filled in). |
| GET    | `/api/v1/modules/machine/settings/{k}`     | Single key, `404` if missing. |
| PUT    | `/api/v1/modules/machine/settings`         | Replace payload, returns merged result. |
| PUT    | `/api/v1/modules/machine/settings/{k}`     | Upsert single key, returns merged result. |

The four `settings` endpoints are mounted by `ModuleRegistry._mount` —
this module does not define a settings router of its own.

## Safety contract — 500 ms keep-alive watchdog

`MachineModule.on_load` starts the watchdog task defined in
`jog_watchdog.py`. The watchdog wakes every 100 ms and force-stops
any axis whose last keep-alive ping is older than
`jog_watchdog_timeout_ms` (default 500 ms, configurable via
`PUT /api/v1/modules/machine/settings/jog_watchdog_timeout_ms`).

The watchdog reads the timeout **once** at startup; mid-flight changes
take effect on the next backend restart. This matches the documented
v1 behaviour from `MODULE_SYSTEM_ROADMAP.md § 4`.

`MachineModule.on_unload` cancels the watchdog and clears the
`_active_jogs` map so the next boot starts clean (the
`jog_watchdog.stop_watchdog()` helper is idempotent under
`uvicorn --reload`).

## Lifecycle

* `on_load(ctx)` reads the configured watchdog timeout from
  `ctx.settings`, then schedules `_loop()` as an asyncio task.
* `on_unload()` cancels the task and clears `_active_jogs`. Safe to
  call multiple times — the helpers are idempotent.

## Settings schema

`MachineSettings` (`pydantic.BaseModel`):

| Field                    | Type  | Default | Bounds            | Description |
|--------------------------|-------|---------|-------------------|-------------|
| `jog_watchdog_timeout_ms`| int   | 500     | 100 — 5 000       | Continuous-jog watchdog window. |
| `default_jog_velocity`   | float | 500.0   | `>= 1.0`          | Default velocity for a fresh continuous jog. |
| `keepalive_interval_ms`  | int   | 250     | 50 — 2 000        | Frontend-side keep-alive cadence hint. |
| `estop_disables_power`   | bool  | True    | —                 | Whether engaging E-STOP also drops power. |

The schema is consumed by `SettingsStore(defaults=…)` so new keys
appear automatically on the next `read_all` without forcing a
migration of the persisted JSON file.

## Manual smoke test

```bash
# 1. Defaults
curl -s http://localhost:8000/api/v1/modules/machine/settings | jq
# => {"jog_watchdog_timeout_ms":500,"default_jog_velocity":500.0,
#     "keepalive_interval_ms":250,"estop_disables_power":true}

# 2. Update a single key
curl -s -X PUT -H 'Content-Type: application/json' \
  -d '{"default_jog_velocity": 750}' \
  http://localhost:8000/api/v1/modules/machine/settings/default_jog_velocity | jq

# 3. Jog smoke test (continuous jog on X axis)
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"velocities":{"0":1000},"distance":0}' \
  http://localhost:8000/api/v1/modules/machine/jog | jq
# Without a follow-up keep-alive, the watchdog force-stops the axis
# within 500 ms. The backend log shows
#     SAFETY WATCHDOG: missed keep-alive on axis 0 — STOP
```

## Nullable-module guarantee

Removing both `backend/modules/machine/` and
`frontend/src/modules/machine/` is the documented happy path:

* Backend boots with `registry: mounted=['camera','temperature','program']`
  (machine is gone).
* The frontend dashboard's `DashboardView.vue` skips the DRO and
  JogControls slots because `registry.modules.has('machine')` returns
  `false`; the slots render the placeholder cards.
* `npm run build` still succeeds because the Vite glob is lazy
  (`import.meta.glob('../../modules/*/index.js', { eager: false })`)
  and the legacy shim at `frontend/src/stores/machine.js` re-exports
  the new module's store under the legacy import path.
* See `MODULE_SYSTEM_ROADMAP.md § 12 Gotcha #1` for the design
  rationale.

## Known caveats

* Hot-reload under `uvicorn --reload` clears the `_active_jogs` map
  on `on_unload` so the next boot does not resume a jog whose
  keep-alive trail was lost when the watchdog task was cancelled.
* The watchdog hard-caps its own lifetime at 10 minutes per loop; a
  wedged task exits and the next `start_watchdog` spawns a fresh
  one. This bounds the impact of a buggy loop in CI / test
  environments without affecting production (the watchdog is
  long-lived but never blocked on anything except `asyncio.sleep`).
* The legacy URL paths (`/api/v1/machine/...`) are gone — every
  frontend call now goes through `/api/v1/modules/machine/...`.
  The generated OpenAPI client was updated as part of this
  migration; regenerate it after any further endpoint change.
