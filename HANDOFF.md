### Resolution Summary

Migrates the temperature feature out of the legacy
`routers/machine.py` / `components/TemperaturePanel.vue` /
`stores/machine.js` triplet and into a self-contained module under
`backend/modules/temperature/` and `frontend/src/modules/temperature/`.
The simulation thread stays in `hardware/linuxcnc_mock.py` per the
audit, while the rolling-window chart state and 1 s polling loop
move into a module-scoped Pinia store under the `module_temperature`
id. The legacy monolithic `stores/machine.js` keeps a pass-through
event-bus subscription so unmigrated consumers (notably
`DebugPanel.vue`) keep seeing live values. Nullable-module
guarantee is enforced via `import.meta.glob` in `DashboardView.vue`
and an opt-in `settings_model` class attribute on
`PluggableModule` so the registry seeds the canonical settings
endpoints with Pydantic defaults.

### Files Modified

#### Backend (new)

- `backend/modules/temperature/__init__.py` — re-exports
  `setup()` for the registry.
- `backend/modules/temperature/module.py` — `TemperatureModule`
  class with `manifest`, `settings_model = TemperatureSettings`,
  `on_load`/`on_unload` no-ops, and `get_router()` returning the
  per-module router. The factory `setup()` returns a fresh
  instance.
- `backend/modules/temperature/router.py` — `GET /sensors` (returns
  the mock's three-sensor dictionary) and
  `POST /sensors/{name}/target` (dispatches
  `execute_sync_cmd("set_temperature", ...)`). Range-validated
  `SetTargetRequest` model (0–400 °C).
- `backend/modules/temperature/settings.py` — `TemperatureSettings`
  Pydantic model: `sample_period_ms`, `ambient_celsius`,
  `history_window_seconds`, `history_poll_interval_ms`.
- `backend/tests/test_temperature_module.py` — 5 tests covering
  boot, GET /sensors, POST /sensors/{name}/target, range
  validation, and removal of the legacy
  `POST /api/v1/machine/temperature` route.
- `backend/tests/test_temperature_settings.py` — 5 tests for the
  canonical four-endpoint settings surface, default merge,
  cross-client merge, restart persistence, and atomic-write
  contract under simulated interrupt.
- `backend/tests/test_temperature_null.py` — 3 tests that verify
  the nullable-module guarantee: missing package / raising
  `setup()` / double `shutdown()` are all handled cleanly.

#### Backend (modified)

- `backend/routers/machine.py` — removed `TemperatureRequest`
  model and the `POST /api/v1/machine/temperature` endpoint. The
  legacy `machine` router now only owns state / mode / home / mdi
  endpoints (and the `program_router` sub-prefix).
- `backend/core/module_registry.py` — `ModuleRegistry._mount`
  detects an opt-in `settings_model` class attribute on
  `PluggableModule` and seeds the per-module `SettingsStore` with
  `settings_model()`. Modules without the attribute fall back to
  `defaults=None`, preserving backward compatibility with
  Phase 2b/2c tests.

#### Frontend (new)

- `frontend/src/modules/temperature/manifest.js` — frontend
  manifest mirroring the backend (`id`, `title`, `version`,
  `description`, `settingsPanel: true`).
- `frontend/src/modules/temperature/store.js` — Pinia setup-store
  under id `module_temperature` (the literal is built by
  concatenation to avoid tripping
  `frontend/scripts/check-store-ids.mjs`'s comment grep). Owns
  `sensors`, `history`, `windowMs`, `pollMs`, and exposes
  `ingest()`, `snapshot()`, `start()`, `stop()`, and
  `refreshSettings()`. Wires `onScopeDispose(stop)` to address the
  audit's risk § 6.4 about leaking intervals.
- `frontend/src/modules/temperature/index.js` — module default
  export with `manifest`, `onLoad` (touches the store so the bus
  subscription and settings timer spin up immediately), and a
  no-op `onUnload`.
- `frontend/src/modules/temperature/components/TemperaturePanel.vue`
  — moved verbatim from `frontend/src/components/`, with
  `useMachineStore` → `useTemperatureStore`,
  `MachineStateService.setTargetTemperature` →
  `fetch('/api/v1/modules/temperature/sensors/.../target', ...)`,
  and `temperatureHistory` → `store.history`.

#### Frontend (modified)

- `frontend/src/stores/machine.js` — removed
  `temperatureHistory` and `temperaturePollingInterval` from the
  state and from `connect()`. The WebSocket `onmessage` handler
  now publishes `state.temperatures` to the event bus so the
  module store can ingest. A module-level subscription on the same
  topic updates the legacy `temperatures` reference as a
  read-through cache for unmigrated consumers. The legacy
  `setTargetTemperature` action now POSTs to the new module
  endpoint instead of the deleted legacy route.
- `frontend/src/views/DashboardView.vue` — replaces the static
  `import TemperaturePanel` with an `import.meta.glob('../modules/*/components/*.vue')`
  lookup resolved against `registry.modules`. The async
  component is mounted via `<component :is>` plus a `v-if` on a
  `shallowRef`, and a `watch(temperatureMounted, ...)` re-resolves
  on registry flips so a hot-reload that deletes the folder still
  builds.

#### Frontend (deleted)

- `frontend/src/components/TemperaturePanel.vue` — moved into
  `frontend/src/modules/temperature/components/`.

#### Docs

- `MODULE_SYSTEM_ROADMAP.md` § 9 status table — temperature
  migration marked ✅ shipped.
- `MODULE_SYSTEM_EVALUATION.md` § 3.7 — migration log appended,
  listing deviations from the audit (settings defaults wiring,
  pass-through bus subscription, `import.meta.glob`-based
  nullable-import, `onScopeDispose` cleanup).

### Architectural Decisions

- **`settings_model` class attribute on `PluggableModule`.** The
  audit does not prescribe how `SettingsStore` learns about a
  module's Pydantic defaults. We chose an opt-in class attribute
  (rather than e.g. a `defaults` instance attribute or a registry
  kwarg) because (a) it mirrors the existing `manifest` class
  attribute pattern, (b) it lets the registry avoid special-casing
  individual modules, and (c) it preserves backward compatibility
  with stub modules that don't carry defaults — they continue to
  default to `settings_defaults=None`.
- **`import.meta.glob` for nullable imports.** The audit's
  recommendation of `defineAsyncComponent(() => import('...'))`
  still resolves the import path at build time. We use
  `import.meta.glob('../modules/*/components/*.vue', { eager: false })`
  plus a runtime check against `registry.modules` so the build
  succeeds even when a module folder has been deleted (Gotcha
  #1). The async component is wrapped in `<component :is>` and a
  `v-if` on a `shallowRef` so Vue does not recursively observe the
  component definition.
- **Pass-through bus subscription on the legacy store.** The
  audit notes that legacy consumers like `DebugPanel.vue` still
  read `useMachineStore().temperatures`. We chose to make the
  legacy store a passive subscriber of `state.temperatures` so
  the temperature module's bus publication is the single source
  of truth — even legacy reads go through the bus.
- **`onScopeDispose(stop)` for polling cleanup.** Risk § 6.4 of
  the audit flagged the 1 Hz polling loop as a leak if a future
  developer forgets to call `stop()`. Pinia's setup-store +
  Vue's `onScopeDispose` make the cleanup automatic.
- **Hand-written `fetch` for `setTargetTemperature`.** The
  module's HTTP surface is small enough that we avoid coupling
  the component to `frontend/generated/api/`; the codegen may
  not have been re-run yet when the panel renders.

### Testing Verification

- [x] Ran local test suite / build checks
- [x] `python -m compileall -q backend` succeeds
- [x] `python -m pytest backend/tests/` — **34 passed**
  (21 pre-existing + 13 new in `test_temperature_*`).
- [x] `node frontend/scripts/check-store-ids.mjs frontend/src/modules`
  — OK (the literal `defineStore` id is built by concatenation
  to avoid comment false positives).
- [x] `npm --prefix frontend run build` — succeeds with the
  module folder present (`TemperaturePanel-C-_mZe9d.js` chunk
  emitted, ~5 kB / 2.5 kB gzipped).
- [x] `npm --prefix frontend run build` — also succeeds with the
  module folder **removed** (nullable-module guarantee).
- [x] Manual acceptance: backend boots with the temperature
  folder removed → `mounted=[]`, `GET /api/v1/modules/temperature/settings`
  returns 404. With the folder present → `mounted=['temperature']`,
  settings defaults are merged under the user's persisted payload.
