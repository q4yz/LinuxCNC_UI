# Module System — Code State Evaluation

> **Status:** internal audit. No implementation work here.
> **Date:** 2026-07-15.
> **Scope:** the camera, temperature, and axis (DRO + jog) features; the
> LinuxCNC mock; and the cross-cutting concerns that block a clean
> migration into the module system.

This is the companion audit to [`MODULE_SYSTEM_ROADMAP.md`](MODULE_SYSTEM_ROADMAP.md)
and [`MODULE_SYSTEM_ISSUE_01.md`](MODULE_SYSTEM_ISSUE_01.md). Where the roadmap
defines the destination and Issue #01 defined the core infrastructure,
this document evaluates **what's actually on disk today** and identifies
the pitfalls we will hit when migrating camera, temperature, and axis.

---

## 0. Headline finding

**Phase 2b/2c is already implemented and wired in.** The roadmap's
"core infrastructure" issue is functionally complete. What remains:

| Phase | Status | What's missing |
|---|---|---|
| 2a (doc cleanup, `.agent/` folder) | ❌ Not done | Folder doesn't exist; `AI_INSTRUCTIONS.md` still at root; contracts not authored as standalone files |
| 2b (registry skeleton) | ✅ Done | `core/protocols.py`, `core/module_registry.py` both present and used by `main.py` |
| 2c (settings skeleton) | ✅ Done | `core/settings_store.py` + `core/modules/settings.js` + `SettingsView.vue` placeholder present |
| 2d (camera migration) | ❌ Not done | `backend/modules/camera/` does not exist; `CameraPanel.vue` still in flat `components/` |
| 3 (other routers) | ❌ Not done | All flat routers still mounted by static `include_router` in `main.py` |
| 3a (machine migration) | ❌ Not done | WebSocket transport still in `routers/`; telemetry not yet a module concern |
| 4 (subscription telemetry) | ❌ Not done | `stores/machine.js` still owns the WebSocket client |
| 5 (form-from-schema settings) | ❌ Not done | `SettingsView.vue` is a placeholder; manifests don't carry schemas |
| 6 (SQLite promotion) | ❌ Not done | N/A — no module needs it yet |

**One-line summary:** the plumbing exists; no feature has been migrated
through it. The migration is exactly what the roadmap predicted would be
the next concrete step.

---

## 1. What's already implemented (verified)

### 1.1 Backend `core/` inventory

| File | Lines | Role |
|---|---|---|
| `backend/core/protocols.py` | ~190 | `PluggableModule` `@runtime_checkable` Protocol, `ModuleManifest`, `SidebarEntry`, `ModuleContext` dataclass, `ModuleFactory` callable type |
| `backend/core/module_registry.py` | ~340 | `ModuleRegistry` class + module-level `registry` singleton. Discovers via `pkgutil.iter_modules`, filters by `MODULES_ENABLED`, mounts routers + canonical settings router under `/api/v1/modules/{id}/settings`, calls `on_load` / `on_unload`. Logs `registry: mounted=[] skipped=N missing=M`. |
| `backend/core/event_bus.py` | ~170 | `EventBus` class + module-level `bus` singleton. Async pub/sub, deep-copies Pydantic payloads before fan-out (Gotcha #3), rate-limits `state.*` topics via equality cache. |
| `backend/core/settings_store.py` | ~210 | `SettingsStore` per-module JSON at `data/modules/<id>/settings.json`. Atomic `tmp + os.replace`. In-memory cache. Default merge on read. |
| `backend/core/telemetry/bus.py` | (exists) | (Shallow — see § 5.2) |
| `backend/core/telemetry/__init__.py` | (exists) | Package marker |

### 1.2 Backend wiring (verified in `backend/main.py`)

```python
from core.module_registry import registry
...
async def lifespan(app: FastAPI):
    ...
    registry.boot(app)
    app.state.module_registry = registry
    yield
    registry.shutdown()
```

Both the registry boot **and** the legacy static `include_router` calls
coexist. This is exactly what Issue #01's acceptance criteria required.

### 1.3 Frontend `core/modules/` inventory

| File | Role |
|---|---|
| `frontend/src/core/modules/protocols.js` | JSDoc typedefs for `FrontendModule`, `ModuleContext`, `SidebarEntry`. (No actual TS, but TypeScript-grade contracts via JSDoc.) |
| `frontend/src/core/modules/registry.js` | `FrontendRegistry` class + singleton. Uses **`import.meta.glob('../modules/*/index.js', { eager: false })`** — Gotcha #1 correctly handled. Soft-whitelist via `MODULES_ENABLED` / `VITE_MODULES_ENABLED`. |
| `frontend/src/core/modules/event-bus.js` | Frontend `EventBus` mirror of the backend one. |
| `frontend/src/core/modules/telemetry-bus.js` | WebSocket client wrapper. |
| `frontend/src/core/modules/settings.js` | `createModuleSettings(id)` factory producing a typed `ModuleSettingsApi`. |

### 1.4 Frontend wiring (verified in `frontend/src/main.js` + `AppSidebar.vue`)

- `main.js` imports the registry, calls `registry.boot()` (fire-and-forget)
  **after** `app.mount('#app')`, so the shell renders immediately.
- `AppSidebar.vue` already reads `registry.sidebarEntries()` via a
  `computed()` and merges it with the static built-in nav list.
- `SettingsView.vue` already iterates `registry.settingsPanels()` and
  renders the empty-state placeholder when the registry is empty.

### 1.5 Discovery folders exist but are empty

```text
backend/modules/
├── __init__.py
└── README.md        # explains "intentionally empty until migration begins"
frontend/src/modules/
└── README.md        # ditto
```

The nullable-module guarantee is already validated: deleting these
folders entirely, or leaving them empty, is the documented happy path.

---

## 2. Audit — camera

**Verdict: cleanest migration. Lowest risk. Recommended first.**

### 2.1 Backend surface

`backend/routers/camera.py` (~60 lines):

- One router, prefix `/api/v1/camera`.
- One endpoint: `GET /stream` returning an MJPEG `StreamingResponse`.
- All state is **module-private**: `_latest_frame`, `_camera_thread`,
  `_camera_lock` are module-level globals. **No** cross-cutting state,
  no shared hardware singleton, no EventBus usage.
- Hardware (USB webcam via OpenCV `cv2.VideoCapture`) is opened inside
  the module's own background thread.

**Migration shape:**

```
backend/modules/camera/
├── __init__.py        # re-exports setup()
├── module.py          # CameraModule(PluggableModule) + manifest + get_router()
├── router.py          # StreamingResponse endpoint + background frame thread
├── settings.py        # Pydantic CameraSettings (resolution, jpeg_quality, target_fps)
└── README.md
```

The `Camera` class will own its own `_camera_thread` lifecycle via
`on_load` / `on_unload`. The 4 canonical settings endpoints are mounted
automatically by the registry.

### 2.2 Frontend surface

`frontend/src/components/CameraPanel.vue` (~60 lines):

- Single `<img :src="streamUrl">` against the MJPEG endpoint.
- Uses an inline cache-busting `?t=…` query string.
- Has its own local `hasError` ref + retry button. **No** Pinia store,
  **no** API client usage.

**Migration shape:**

```
frontend/src/modules/camera/
├── index.js           # exports { manifest, onLoad, sidebar, ... }
├── api.js             # (probably empty — no JSON endpoints)
└── components/
    └── CameraPanel.vue
```

### 2.3 Settings story (new for camera)

The current camera has **no settings**. The migration is a good moment
to introduce them. Suggested schema:

```python
class CameraSettings(BaseModel):
    device_index: int = 0             # which /dev/videoN
    width: int = 640
    height: int = 480
    jpeg_quality: int = 70            # 0-100
    target_fps: int = 15              # cap client stream framerate
```

These currently live as hard-coded values in `routers/camera.py`
(`cap.set(...)`, the encode parameter, the `time.sleep(0.06)`). The
migration extracts them into the schema and lets the module read from
its `SettingsStore` on each frame.

### 2.4 Pitfalls for camera

1. **OpenCV lifecycle in `on_load`.** The current `cap = cv2.VideoCapture(0)`
   is opened lazily inside `_camera_worker()`. The module should open in
   `on_load()` and **release in `on_unload()`** — otherwise hot-reload
   during dev will leak file descriptors.
2. **StreamingResponse + FastAPI lifespan.** The current generator is
   `async def generate_frames()` — under FastAPI lifespan it can outlive
   the worker thread on shutdown. Mitigation: `on_unload()` must cancel
   the thread **and** drain pending generators by closing the underlying
   `cap`.
3. **Cache-buster query param.** Frontend uses `?t=Date.now()`. The
   Vite proxy will not break this; the backend should preserve it.
4. **`<img>` element does not gracefully close the MJPEG stream.** When
   the user navigates away, the connection hangs until the socket times
   out. Low priority but worth a TODO.

### 2.5 Mock impact

**None.** The mock (`linuxcnc_mock.py`) does not simulate a camera; the
module talks to OpenCV directly.

### 2.6 Migration log (Phase 2d, issue #31)

The camera migration landed in four stages:

1. **Pluggable protocol extension.** The `PluggableModule` Protocol
   gained an *optional* `get_settings_model()` hook so modules can
   declare the Pydantic defaults the registry forwards to
   `SettingsStore`. The hook is optional: existing modules keep
   working unchanged because the registry uses `getattr` with a
   `None` fallback. See `core/protocols.py` and the helper
   `ModuleRegistry._resolve_settings_model` in
   `core/module_registry.py`.
2. **Module package.** `backend/modules/camera/` contains
   `__init__.py` (re-export `setup`), `module.py` (`CameraModule` +
   `ModuleManifest`), `router.py` (`CameraWorker` + `/stream` +
   `/status` endpoints) and `settings.py` (`CameraSettings` with the
   five knobs — `device_index`, `width`, `height`, `jpeg_quality`,
   `target_fps`). The legacy `backend/routers/camera.py` was deleted
   and `backend/main.py` no longer imports it.
3. **Frontend module.** `frontend/src/modules/camera/` contains
   `index.js`, `manifest.js`, and `components/CameraPanel.vue`. The
   legacy `frontend/src/components/CameraPanel.vue` was deleted and
   `DashboardView.vue` now loads the panel via
   `defineAsyncComponent` behind a `v-if="cameraMounted"` guard so
   deleting `frontend/src/modules/camera/` produces an empty cell,
   not a build error.
4. **Tests.** `backend/tests/test_camera_module.py`,
   `test_camera_settings.py`, and `test_camera_null.py` exercise the
   module, the settings endpoints, and the nullable-module guarantee.
   `frontend/tests/test-registry.mjs` and `test-camera-null.mjs` cover
   the corresponding frontend contracts using the existing pure-Node
   `node --test` pattern.

**Deviations from the audit plan:**

* The audit suggested opening the `cv2.VideoCapture` inside `on_load`
  and releasing it in `on_unload`. We kept the lazy open-on-first-
  stream behaviour of the legacy router because the dashboard may
  boot on a headless deployment (CI, Vite preview server) where no
  camera is attached and the `/stream` endpoint is never hit. The
  worker logs and disables itself cleanly if OpenCV is missing or the
  device index is invalid. The trade-off is documented in
  `backend/modules/camera/README.md` and the lazy behaviour is
  covered by the existing `CameraModule.on_unload` idempotency test.
* The audit mentioned a `Camera` class; the implementation uses a
  `CameraWorker` class to disambiguate from the global `cv2` import.
* The `SidebarEntry.icon` for the camera module is an inline SVG of
  a video camera glyph (consistent with the built-in icons). The
  issue's "…" placeholder was kept abstract on purpose; we ship a
  concrete icon so the sidebar renders correctly without further work.
* The `console.js` Pinia store refactor (§ 8 open question #3) was
  **not** picked up in this migration because the camera module has
  no console integration. It will be revisited when the temperature
  or axis migration lands.

---

## 3. Audit — temperature

**Verdict: medium risk. Touches shared mock state + telemetry + a
chart polling loop. Schedule after camera.**

### 3.1 Backend surface — fragmented across three files

| File | Lines | What it owns |
|---|---|---|
| `backend/routers/machine.py` | ~200 | `POST /api/v1/machine/temperature` endpoint (`set_temperature`) |
| `backend/hardware/linuxcnc_mock.py` | ~440 | `SharedMachineState.temperatures` dict + `_temp_simulation_loop()` thread + `command.set_temperature(sensor_name, temp)` |
| `backend/routers/websocket.py` | ~200 | `get_current_state()` emits the `temperatures` dict + single-sensor compat fields (`target_temp`, `actual_temp`) |

The temperature endpoint sits in `routers/machine.py` alongside the
machine-state endpoints — it was originally a Klipper-style command
that the project added to LinuxCNC, so it lives in the "machine" router
by historical accident.

### 3.2 Frontend surface — also fragmented

| File | Lines | What it owns |
|---|---|---|
| `frontend/src/components/TemperaturePanel.vue` | ~190 | UI: per-sensor cards + ECharts line chart of `temperatureHistory` |
| `frontend/src/stores/machine.js` | ~400 | Imports `MachineStateService.setTargetTemperature` (line ~360); owns `temperatureHistory` rolling 10-second window + the **1-second polling interval** that snapshots into `temperatureHistory` |
| `frontend/src/components/ConsolePanel.vue` | (small) | Indirectly reads `useMachineStore` for `errors` |

### 3.3 Data flow today (and where it breaks)

```text
[user input "Set" 200°C]
       │
       ▼
TemperaturePanel.vue ── MachineStateService.setTargetTemperature()
       │
       ▼
POST /api/v1/machine/temperature  (routers/machine.py)
       │
       ▼
hardware.execute_sync_cmd("set_temperature", 0, sensor, value)
       │
       ▼
linuxcnc_mock.command.set_temperature(sensor_name, value)
       │
       ▼
SharedMachineState.temperatures[sensor]["target"] = value
       │
       ▼
_temp_simulation_loop() (1 Hz) ticks each sensor toward target
       │
       ▼
SharedMachineState.temperatures[sensor]["actual"] += …
       │
       ▼ (every 100 ms)
websocket.get_current_state() reads stat.temperatures
       │
       ▼
WebSocket broadcast (delta or full_state)
       │
       ▼
frontend stores/machine.js  merges delta into status.temperatures
       │
       ▼ (1 s polling interval)
temperatureHistory.push({ time, sensors: JSON.parse(JSON.stringify(temperatures)) })
       │
       ▼
TemperaturePanel.vue  chartOptions consumes temperatureHistory
```

**The pollution is the `temperatureHistory` polling interval that lives
inside the monolithic `stores/machine.js`.** Migrating the temperature
module means moving that interval into the temperature module's Pinia
store.

### 3.4 Migration shape

```
backend/modules/temperature/
├── __init__.py
├── module.py          # TemperatureModule + manifest
├── router.py          # POST /set, GET /sensors, POST /sensors/{name}/off
├── settings.py        # TemperatureSettings (sample_period_ms, ambient_celsius)
└── README.md

frontend/src/modules/temperature/
├── index.js
├── store.js           # defineStore('module_temperature', ...) — owns temperatureHistory
├── api.js             # typed wrapper around ModuleTemperatureService
└── components/
    └── TemperaturePanel.vue
```

### 3.5 Pitfalls for temperature

1. **Single-sensor compat fields.** `SharedMachineState.target_temp` and
   `actual_temp` are maintained in lock-step with the `extruder` entry
   of `temperatures`. The WebSocket emitter still broadcasts them as
   top-level fields. After migration, the `machine` telemetry still
   needs to keep emitting them (backward-compat with consumers that
   haven't migrated yet), **and** the temperature module can additionally
   publish a typed `state.temperatures` event on the bus.
2. **The 1-second polling loop in `stores/machine.js`.** It currently
   lives at lines ~135–150 of `machine.js`, guarded by a boolean flag
   `temperaturePollingInterval`. After migration this **must** move to
   `frontend/src/modules/temperature/store.js` — otherwise deleting the
   temperature module folder breaks the dashboard because
   `temperatureHistory` would never be populated.
3. **`Mock state coupling`.** `_temp_simulation_loop()` runs as a daemon
   thread tied to `_machine_state.temp_thread`. The thread must keep
   running for as long as the **process** is alive, not for as long as
   the temperature module is mounted. Mitigation: keep the simulation
   thread in `hardware/linuxcnc_mock.py` (which the module imports via
   `core.protocols`); do not move it to the module. The module only
   publishes its current sensor list to the bus; the simulation stays
   in core.
4. **Command interface.** `command.set_temperature(sensor_name, temp)`
   is a non-standard command on the real `linuxcnc` Python binding.
   Today the call works only because the fallback to `linuxcnc_mock` is
   in effect. Real-hardware migration is out of scope for the module
   migration but worth a TODO.
5. **Console integration.** `setTargetTemperature` action (machine store
   line ~360) posts a console message. After migration, the
   temperature module's store should import `useConsoleStore` from a
   shared `core/stores/console.js` location (currently
   `stores/console.js`). This is the same console store used by all
   modules — fine, no duplication, but the import path needs to be
   stable.

### 3.6 Mock impact

**Limited but real.**

- `SharedMachineState.temperatures` and the `_temp_simulation_loop()`
  thread **stay in** `linuxcnc_mock.py`. The simulation must outlive
  the module because the mock is a process-wide concern.
- `command.set_temperature(sensor_name, temp)` stays in
  `linuxcnc_mock.py`. It mutates `SharedMachineState.temperatures` and
  starts the simulation thread on first call. The temperature module's
  router endpoint calls this method via `execute_sync_cmd("set_temperature", ...)`.
- `stat.temperatures` shallow-copy in `_update_attrs()` stays.
- What moves: **none** of the mock code. Only the HTTP endpoint that
  triggers `set_temperature` moves to the module.
- What must be added later (out of scope here): a separate
  `core/hardware/mock_temperature.py` if we ever want the temperature
  module to be removable from the mock too. Not needed for v1.

### 3.7 Migration log — issue #32 (shipped)

Status: **shipped**. The temperature module now lives under
`backend/modules/temperature/` and `frontend/src/modules/temperature/`.
Five acceptance criteria from the issue are all met:

1. Registry mounts `['camera', 'temperature']` on a clean checkout
   with `MODULES_ENABLED` empty.
2. `GET /api/v1/modules/temperature/sensors` returns the mock's
   three-sensor dictionary.
3. `PUT /api/v1/modules/temperature/settings` persists
   `history_window_seconds` and survives a backend restart (verified
   by `test_temperature_settings.py::test_settings_survive_restart`).
4. Removing both module folders leaves the registry at
   `mounted=['camera']` (or `[]` if camera is also removed) with no
   error logs.
5. `npm run build` succeeds with both folders deleted (verified
   manually during PR review).

#### Deviations from the audit's plan

- **Settings defaults wiring.** The audit did not prescribe how
  `SettingsStore` would learn about a module's Pydantic defaults
  model. The shipped implementation adds an opt-in `settings_model`
  class attribute on `PluggableModule`; `ModuleRegistry._mount`
  detects it and seeds the per-module store with `defaults=instance()`.
  Modules that omit the attribute (e.g. the camera stub) fall back
  to `defaults=None`, preserving backward compatibility with the
  Phase 2b/2c tests in `test_module_registry.py`.
- **Pass-through bus subscription.** The legacy `stores/machine.js`
  keeps a `state.temperatures` subscription so unmigrated consumers
  (`DebugPanel.vue`, third-party widgets) see live values. The
  audit did not call this out explicitly; it became necessary when
  the legacy store no longer maintained `temperatureHistory`
  itself.
- **Nullable-import via `import.meta.glob`.** The audit recommended
  `defineAsyncComponent` for the panel; we use a slightly richer
  pattern with `import.meta.glob('../modules/*/components/*.vue')`
  so the dashboard builds even when a module folder has been
  deleted (Gotcha #1). The async component is wrapped in
  `<component :is>` plus a `v-if` on a `shallowRef` that only
  resolves after the registry boots.
- **`onScopeDispose` polling cleanup.** Risk § 6.4 from the audit
  flagged the polling loop as a potential leak if `stop()` were
  never called. The shipped store wires `onScopeDispose(stop)` so
  the polling interval is torn down automatically when the pinia
  scope ends.
- **Pydantic defaults merged under legacy tests.** The existing
  `test_module_registry.py::test_settings_router_mounted_under_modules_id_settings`
  test asserts `r.json() == {}` for a stub without defaults.
  Adding `settings_model` support did **not** break that test
  because stub modules don't expose the attribute, and the
  registry defaults to `settings_defaults=None` when the attribute
  is absent.

#### Files touched

- Backend (new): `backend/modules/temperature/{__init__,module,router,settings}.py`.
- Backend (modified): `backend/routers/machine.py` (removed
  `TemperatureRequest` model and `POST /api/v1/machine/temperature`
  endpoint), `backend/core/module_registry.py` (added
  `settings_model` opt-in for module defaults).
- Backend (tests): `backend/tests/test_temperature_{module,settings,null}.py`.
- Frontend (new): `frontend/src/modules/temperature/{index,manifest,store}.js`
  + `components/TemperaturePanel.vue`.
- Frontend (modified): `frontend/src/stores/machine.js` (removed
  `temperatureHistory` and `temperaturePollingInterval`, added bus
  publish/subscribe pass-through, repointed
  `setTargetTemperature` to the module's HTTP endpoint),
  `frontend/src/views/DashboardView.vue` (lazy-load via
  `import.meta.glob` + nullable-import guard).
- Frontend (deleted): `frontend/src/components/TemperaturePanel.vue`
  (moved to the module folder).
- Docs: `MODULE_SYSTEM_ROADMAP.md` § 9 status table updated.

---

## 4. Audit — axis (DRO + jog + machine state + MDI + home)

**Verdict: highest risk. Safety-critical keep-alive/watchdog, tightly
coupled to the monolithic store, and shares the mock's jog simulation
thread.**

### 4.1 Backend surface — split across two routers + the mock

| File | Lines | What it owns |
|---|---|---|
| `backend/routers/machine.py` | ~200 | `POST /state`, `POST /mode`, `POST /home`, `POST /mdi` + the `program_router` (run/stop/pause/resume/parse) |
| `backend/routers/jog.py` | ~165 | `POST /jog`, `POST /jog/keepalive`, `POST /jog/stop` + the **safety watchdog** background task |
| `backend/hardware/linuxcnc_mock.py` | ~440 | `SharedMachineState.{jogging_axis, jogging_velocity, jog_thread, jog_stop_event}` + `_jog_simulation_loop()` |

### 4.2 The safety-critical watchdog

`backend/routers/jog.py` line ~70 runs an `async def jog_watchdog()`
that:

1. Every 100 ms, scans `active_jogs` (a process-global dict keyed by
   axis index → last-ping timestamp).
2. Any axis that hasn't been pinged within **500 ms** is force-stopped
   via `_stop_axis()`.
3. Spawned from `main.py` lifespan as `task_watchdog`.

This is **safety-critical**: a UI bug that leaks a continuous jog could
otherwise move the spindle indefinitely. The watchdog **must** keep
working after migration. Recommendation: keep the watchdog in
`backend/core/telemetry/safety.py` (new) or co-locate it with the
machine module under `backend/modules/machine/jog_watchdog.py`.

### 4.3 Frontend surface — heavily fragmented

| File | Lines | What it owns |
|---|---|---|
| `frontend/src/components/DroPanel.vue` | ~230 | E-STOP / Power banner, DRO X/Y/Z readouts, WCS selector, home-all, per-axis home, "set position" modal |
| `frontend/src/components/JogControls.vue` | ~165 | 6-button jog grid, slider for speed, keyboard bindings (ArrowKeys, PageUp/Down), `onBeforeUnmount` cleanup, `window.blur` stop-all |
| `frontend/src/stores/machine.js` | ~400 | **The whole world**: WebSocket client + reconnect + delta merge + status state + 7 actions (`toggleEstop`, `togglePower`, `jog`, `jogContinuous`, `jogStop`, `homeAxis`, `homeAll`, `setPosition`, `setCoordinateSystem`, `setTargetTemperature`) |

### 4.4 The dashboard hard-imports the panels

```vue
<!-- frontend/src/views/DashboardView.vue -->
import DroPanel from '../components/DroPanel.vue'
import JogControls from '../components/JogControls.vue'
import TemperaturePanel from '../components/TemperaturePanel.vue'
import CameraPanel from '../components/CameraPanel.vue'
```

These are **static imports**. After migration:

- The dashboard **must** move from these static imports to
  `defineAsyncComponent(() => import('@/modules/machine/components/DroPanel.vue'))`,
  or the nullable-module guarantee (Gotcha #1) regresses.
- The dashboard must render a **placeholder card** in the slot a removed
  module would have occupied, so deleting the machine module does not
  break layout. Empty-state-by-id pattern: `v-if="mounted.has('machine')"`.

### 4.5 The monolithic store split

`stores/machine.js` is 400 lines and owns:

- WebSocket transport + reconnect logic
- Status state (positions, homed, g5x_index, task_state, task_mode, …)
- Temperatures state (will move with the temperature module)
- `temperatureHistory` + 1 s polling loop (will move)
- All jog actions + the `jogIntervals` map (will stay in the machine
  module's store, since axis owns jog)
- All home/state/mode actions (will stay in machine module's store)
- E-STOP / Power toggles (will stay in machine module's store)
- Console integration via `useConsoleStore` (shared; ok)

**Splitting plan:**

```
frontend/src/modules/machine/
├── index.js
├── store.js           # defineStore('module_machine', ...)
│                      # owns: status (positions, homed, task_state, etc.)
│                      # owns: jogIntervals
│                      # owns: actions: jog, jogContinuous, jogStop, toggleEstop, …
│                      # owns: connect() — WebSocket subscription
├── api.js             # typed wrappers around ModuleMachineService
└── components/
    ├── DroPanel.vue
    └── JogControls.vue
```

`connect()` becomes **a no-op if the machine module is not mounted**.
Other modules that need telemetry (temperature, files) subscribe to the
event bus for `state.machine.*` events published by the machine module.

### 4.6 Migration shape

```
backend/modules/machine/
├── __init__.py
├── module.py          # MachineModule + manifest
├── router.py          # /state, /mode, /home, /mdi, /jog, /jog/keepalive, /jog/stop
├── jog_watchdog.py    # the 500 ms safety watchdog (move as-is)
├── settings.py        # MachineSettings (jog_watchdog_timeout_ms, default_jog_velocity)
└── README.md

frontend/src/modules/machine/
├── index.js
├── store.js
├── api.js
└── components/
    ├── DroPanel.vue
    └── JogControls.vue
```

`backend/routers/machine.py` splits into:
- `machine` module (above) — the **runtime** state
- `program` module (Phase 3) — run/stop/pause/resume/parse

### 4.7 Pitfalls for axis

1. **The watchdog must outlive the module.** `jog_watchdog` reads
   `active_jogs` from `routers/jog.py`'s module-level state. After
   migration that state moves to the machine module. **Important:**
   `_stop_axis()` on a torn-down module will fail. The watchdog must
   be safe to call even after `on_unload()`. Mitigation: keep the
   watchdog's state (`active_jogs`, the lock) at module scope inside
   `backend/modules/machine/` so the watchdog and the routes share it.
2. **Jog keep-alive interval on the frontend.** `jogIntervals[axis]` is
   a `setInterval` cleared in `jogStop()`. If the user navigates away
   mid-jog, `JogControls.vue`'s `onBeforeUnmount` calls `stopAllJogging`
   — that **must** survive migration. Make sure the unmount handler
   still fires when the panel is hidden via `v-if`, not just when the
   component is destroyed.
3. **Keyboard bindings (`window.addEventListener('keydown')`).** Same
   risk as #2 — they attach at `onMounted` and detach at
   `onBeforeUnmount`. Both must move with the component.
4. **Mock jog simulation thread.** Same principle as temperature sim:
   `_jog_simulation_loop()` is started by `command.jog(JOG_CONTINUOUS)`
   on first use and never stopped (it idles when no axis is being
   jogged). **Stays in `linuxcnc_mock.py`**. The module just calls
   `execute_sync_cmd("jog", ...)` as before.
5. **`store.connect()` is called from `App.vue`'s `onMounted`.** After
   migration, the machine module's `onLoad` hook should perform its
   own `connect()` (or subscribe to the registry's lifecycle), and the
   legacy call in `App.vue` must be removed. Otherwise we'll double-
   subscribe and break the WebSocket diff logic.
6. **Two routers share a prefix.** `routers/machine.py` defines both
   `router` (state/mode/home/mdi/temperature) and `program_router`
   (program lifecycle). After migration: state → `machine` module;
   program → `program` module. Each gets its own prefix under
   `/api/v1/modules/{id}/`. The generated OpenAPI client will expose
   `ModuleMachineService` and `ModuleProgramService` — the frontend
   must migrate from `MachineStateService` to those.
7. **The "set position" modal in `DroPanel.vue`** is MDI under the hood
   (`generateSetOffset(axis, value)` → `G10 L2 P1 X…`). After migration
   this stays in the machine module (it's a runtime action, not a
   configuration).

### 4.8 Mock impact

- `SharedMachineState` global stays. It's the only stateful object the
  simulation threads touch.
- `_jog_simulation_loop()` stays in `linuxcnc_mock.py`.
- `SharedMachineState.{jogging_axis, jogging_velocity, jog_thread, jog_stop_event}`
  stay in `linuxcnc_mock.py`. The module reads them via
  `execute_sync_cmd("jog", ...)` which dispatches to `command.jog()`.
- **What moves:** none of the mock code. The HTTP layer moves.

### 4.9 Migration log — issue #38 (shipped)

Issued as Phase 3a with the highest-risk classification from § 4 of
this evaluation. The audit's plan was followed with three
deviations, all documented here:

* **Generated client URL rewrite** — the audit recommended adding a
  `ModuleMachineService` generated class. The codegen toolchain emits
  `ModulesMachineService` / `ModulesProgramService` for the current
  `modules:<id>` tags, so the live frontend imports those generated
  classes and uses `/api/v1/modules/{id}/...` URLs. A future regen will
  reproduce the same module-scoped paths.
* **`get_settings_model` on `ProgramModule`** — the audit's "no
  settings schema yet" line caused `ProgramModule` to omit the
  method entirely; the runtime `PluggableModule` protocol's
  `isinstance` check required the method to exist (even when it
  returns `None`), so we added an explicit `get_settings_model`
  returning `None`. Behaviour matches the audit; just an explicit
  shape.
* **JogControls `v-if` placeholder wording** — the audit's
  "placeholder cards" guidance used the literal "Machine module not
  mounted." A second placeholder for "Jog controls not mounted."
  was added so the dashboard reveals *which* sub-feature is
  unavailable when only the machine folder has been removed (rare
  but possible if a future refactor splits DRO and jog into
  separate modules).

* **Nullable legacy consumers** — the direct public re-export remains
  available when the module is mounted, but shell components use a
  build-safe compatibility adapter. It delegates to the module store when
  mounted and provides an inert fallback when the optional folder is absent;
  this makes the physical-folder deletion build check meaningful.
* **Lifecycle and safety hardening** — the FastAPI lifespan now calls the
  registry's `shutdown()` API, the watchdog dispatches through the shared
  `_stop_axis` seam, and the frontend cancels reconnect timers on module
  unload. These changes prevent shutdown exceptions, stale sockets, and
  unobservable safety stops.
* **Persisted jog defaults** — `default_jog_velocity` and
  `keepalive_interval_ms` are read from the machine settings surface before
  new jogs start, while retaining the historical safe defaults when the
  module is unavailable.

Other notes:

* The 500 ms keep-alive watchdog is implemented per § 4.2 of this
  audit. `test_jog_watchdog.py` and `test_jog_keepalive.py` cover
  both the regression ("no ping → axis halted within ~600 ms")
  and the happy-path ("every-100 ms ping → axis keeps moving for 2 s")
  scenarios.
* The public `stores/machine.js` path remains a thin re-export for
  third-party consumers while the module is mounted. The shell's internal
  nullable `machine-compat.js` adapter, which delegates to the module store
  when available and is inert when the module is absent.
* `MODULES_ENABLED=camera,temperature` boots cleanly with no
  machine endpoints; `/api/v1/modules/machine/*` returns `404`.
  This is the nullable-module guarantee from § 5.6.
* The dashboard's machine slot renders a placeholder card when
  the registry reports the module absent — verified by
  `frontend/tests/test-machine-null.mjs`.

---

## 5. Cross-cutting pitfalls

These affect every migration, not just one feature.

### 5.1 The generated API client does not know about modules

`frontend/src/services/apiClient.js` imports from
`../../generated/api/services/MachineStateService`. After migration:

- The hand-written client should import from
  `../../generated/api/services/ModuleMachineService` (or whatever the
  backend's new module-scoped tags emit).
- `openapi-typescript-codegen` will regenerate the services based on
  the new tags. Confirm: backend routes under `/api/v1/modules/{id}/…`
  become `Module{Id}Service` (see how the registry tags modules:
  `tags=[f"modules:{module_id}"]`).
- The generator script (`frontend/scripts/generate-api.mjs`) doesn't
  need changes — it regenerates from `/openapi.json` which already
  reflects the mounted module routers.

### 5.2 Telemetry ownership (Phase 4 groundwork)

The WebSocket endpoint at `/ws/telemetry` lives in `routers/websocket.py`
and is **not** part of any module. It broadcasts `state.machine.*` events
keyed on the mock's `stat` object. After migration:

- Either (a) keep the WebSocket transport in `core/telemetry/transport.py`
  and have the **machine module** publish typed events to the bus that
  the transport fans out — this is the Phase 4 design from the roadmap.
- Or (b) keep the existing broadcast path working while the machine
  module independently publishes higher-level typed events to the bus.

Path (b) is recommended for the axis migration; Phase 4 then refactors
the transport without touching module code.

### 5.3 The monolithic frontend store

`frontend/src/stores/machine.js` is referenced from:
`DashboardView.vue`, `DroPanel.vue`, `JogControls.vue`,
`TemperaturePanel.vue`, `ConsolePanel.vue`, `App.vue`, `DebugPanel.vue`.

**Hard truth:** until the machine + temperature modules land, the
monolithic store must remain importable, otherwise the dashboard breaks.
The split is therefore:

1. Migrate the components first; keep `stores/machine.js` as a
   re-export shim that calls into the module stores when present and
   falls back to legacy behaviour otherwise.
2. Once every consumer uses the module stores, delete `stores/machine.js`
   in a follow-up.

This is the same "legacy + module coexisting" pattern the backend
uses with its `include_router` calls.

### 5.4 Settings schemas are not yet on the manifest

Today, `ModuleManifest` carries only `id`, `title`, `version`,
`description`, `sidebar`, `settings_panel`. There's no
`settings_schema: type[BaseModel]` field. The migration issues should
**not** add schemas in this round (that's Phase 5); modules can opt
into the four canonical settings endpoints and let users stuff arbitrary
JSON until the form generator lands.

### 5.5 Pinia store ID convention

The current monolithic `stores/machine.js` uses
`defineStore('machine', …)`. When it splits, the machine module's store
must use `defineStore('module_machine', …)` per Gotcha #2. Same for
temperature: `defineStore('module_temperature', …)`. There is **no
current CI check** for this convention — Issue #01's acceptance
criterion #5 is still open and should be picked up alongside the camera
migration as a CI gating change.

### 5.6 The nullable-module guarantee on the dashboard

The dashboard imports panels statically:

```js
import DroPanel from '../components/DroPanel.vue'
import JogControls from '../components/JogControls.vue'
import TemperaturePanel from '../components/TemperaturePanel.vue'
import CameraPanel from '../components/CameraPanel.vue'
```

If we migrate TemperaturePanel into `frontend/src/modules/temperature/`
without also changing the dashboard, **deleting that folder will fail
the build** (Gotcha #1 violation). The migration of every dashboard
panel must include the dashboard's conversion to
`defineAsyncComponent()` + a placeholder rendering for missing modules.

### 5.7 What's currently broken or fragile

Quick observations during the audit (low priority, but worth logging):

1. `DashboardView.vue` has a stray unused import:
   `import { Camera } from 'three/src/Three.Core.js'`. This is dead code.
2. `CameraPanel.vue` does not import any generated API client — it uses
   raw `<img src>`. After migration to a module folder, this stays a
   raw `<img>` because the stream is MJPEG, not a typed JSON endpoint.
3. `DebugPanel.vue` polls `JSON.parse(JSON.stringify(useMachineStore()))`
   every 3 seconds (per the conversation summary). This is a smell that
   motivates Phase 4 (event-bus subscriptions). Not blocking the migration.
4. The legacy `Backend main.py` imports the static routers (`machine`,
   `jog`, `websocket`, …) **and** boots the registry. Both layers
   coexist. Removing a module after migration must not remove the
   legacy `include_router` until the consumer of that router has
   migrated too.
5. `MODULES_ENABLED` whitelist is "soft" on the frontend (console.warn
   on unknown) and "hard warning log" on the backend. Consider aligning.

---

## 6. Migration order recommendation

Based on coupling and risk:

| Order | Module | Why |
|---|---|---|
| **1st** | camera | Self-contained, no shared state, no telemetry, easy nullable test |
| **2nd** | temperature | Shared mock state but simulation stays in core; main risk is the `temperatureHistory` polling loop |
| **3rd** | machine (axis) | Largest, safety-critical keep-alive/watchdog, owns the WebSocket subscription, drives every other module |
| **4th** | program | Currently `program_router` in `routers/machine.py`; simple once machine is done |
| **5th** | files, system, config, compiler | All backend-only or low-coupling; migrated one at a time |
| **6th** | telemetry refactor (Phase 4) | Decouple the WebSocket from the machine module's Pinia store |

---

## 7. Recommended update to the roadmap

The status table in [`MODULE_SYSTEM_ROADMAP.md`](MODULE_SYSTEM_ROADMAP.md) § 9
should read:

| Phase | Status |
|---|---|
| 1 | ✅ Done |
| 2a | ❌ Not done — pending doc cleanup |
| 2b | ✅ Done — registry + protocols shipped |
| 2c | ✅ Done — settings subsystem + SettingsView shipped |
| 2d | ❌ Not done — tracked by Issue #02 |
| 3 | ❌ Not done — tracked by Issue #03 + #04 |
| 3a | ❌ Not done — covered by Issue #04 |
| 4 | ❌ Not done |
| 5 | ❌ Not done |
| 6 | ❌ Not done |

---

## 8. Open questions surfaced by this audit

1. **Should the temperature module own the simulation thread?** Per § 3.6
   the recommendation is "no, keep in mock", but this means deleting the
   temperature module folder will not stop the simulation — it will keep
   tweaking `SharedMachineState.temperatures` even though no module is
   listening. Acceptable but worth a note.
2. **Where does the WebSocket transport live long-term?** Phase 4
   decision. For now: keep in `routers/websocket.py` as legacy; the
   machine module's `store.connect()` still talks to it.
3. **Should the `console.js` store move to `core/stores/console.js`?**
   Multiple modules need it. Yes — but as a refactor inside the first
   module migration (camera) so we don't keep renaming imports.
4. **How do we test the nullable-module guarantee in CI?** The
   acceptance criterion is a manual check today. Suggest adding a
   build-test step that physically moves each module out, builds, and
   restores.

---

## 9. References

- [`MODULE_SYSTEM_ROADMAP.md`](MODULE_SYSTEM_ROADMAP.md) — overall plan
- [`MODULE_SYSTEM_ISSUE_01.md`](MODULE_SYSTEM_ISSUE_01.md) — core
  infrastructure (now landed in code; this doc still useful as
  contract-of-record)
- [`MODULE_SYSTEM_ISSUE_02_CAMERA_MIGRATION.md`](MODULE_SYSTEM_ISSUE_02_CAMERA_MIGRATION.md)
- [`MODULE_SYSTEM_ISSUE_03_TEMPERATURE_MIGRATION.md`](MODULE_SYSTEM_ISSUE_03_TEMPERATURE_MIGRATION.md)
- [`MODULE_SYSTEM_ISSUE_04_AXIS_MIGRATION.md`](MODULE_SYSTEM_ISSUE_04_AXIS_MIGRATION.md)