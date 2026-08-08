# HANDOFF.md

## Resolution Summary (Issue #97 — dynamic temperature sensors)

The temperature module's sensor list is now driven entirely by the
active `hardware.json` payload instead of a hard-coded
`extruder/bed/cpu` triple. The mock hardware layer, the temperature
module's settings defaults, the `HalCompiler` heater array, and the
frontend store all consume the same dynamic source of truth. Operators
who want a CPU gauge add a `cpu` heater to `machine.cfg`; the legacy
triple is dropped.

### Files Modified / Added (Issue #97)

**Backend**
- `backend/services/hardware_loader.py` (new): shared helper that
  parses `machine_config/active/hardware.json` and returns the
  declared heater names. Falls back to `[]` when the file is
  missing, malformed, or has no `heaters` array.
- `backend/hardware/linuxcnc_mock.py`: removed the hard-coded
  `temperatures = {extruder, bed, cpu}` triple. Now seeds the
  sensor list from the active `hardware.json` via the shared
  helper. Added a public `reseed_from_hardware_json()` so tests
  (and future recompile hooks) can force a re-read without
  re-importing the module. Backwards-compatible `target_temp` /
  `actual_temp` fields mirror the first `extruder`-named sensor
  when one exists, otherwise fall back to safe defaults.
- `backend/services/hal_compiler.py`: `_generate_remora_json` no
  longer emits `heaters: []`. It now parses `MachineConfig.get_heaters()`
  and writes each entry as `{name, control, max_temp, sensor_type}`.
  The legacy `HeaterConfig` / `ExtruderConfig` types are normalised
  to the same shape.
- `backend/modules/temperature/settings.py`: removed the hard-coded
  `extruder/bed/cpu` palette. `TemperatureSettings.sensor_colors`
  defaults to `{}`. Added `seed_colors(heater_names)` helper that
  assigns each name a deterministic colour from a 6-entry palette
  (red, blue, green, amber, violet, pink) in sorted-input order with
  modulo wrap.
- `backend/modules/temperature/module.py`: `__init__` now reads the
  active heater list (called during `setup()` before
  `_resolve_settings_model`); `on_load` re-reads it. The seeded
  `sensor_colors` flow through to the per-module `SettingsStore`.

**Frontend**
- `frontend/src/modules/temperature/store.js`:
  `DEFAULT_SENSOR_COLORS = {}`. The `colorFor` fallback
  (`#A855F7`) remains so any sensor whose persisted colour was
  deleted still renders.

**Tests**
- `backend/tests/test_temperature_module.py`: replaced the static
  `extruder/bed/cpu` assertions with a fixture-driven test that
  drops a fake `hardware.json` with two heaters and asserts the mock
  seeds those two sensors. Added a separate empty-dict test for
  the no-hardware-json path. The `set_target` flow now drives a
  real `heater_bed` sensor so the seed list is non-empty.
- `backend/tests/test_temperature_settings.py`: replaced the
  three-sensor default assertion with an empty-dict assertion plus a
  new "seeded from active heaters" test that drops a three-heater
  `hardware.json` and asserts the seeded palette.
- `backend/tests/test_json_generators.py`: added two new tests
  that drive `HalCompiler._generate_remora_json` against a fixture
  `machine.cfg` declaring `[heater_bed]` + `[extruder]` and assert
  the emitted `hardware.json.heaters` array is non-empty and
  contains the documented fields.

### Architectural Decisions (Issue #97)

- **Shared helper in `services/hardware_loader.py`.** Both the
  mock layer and the temperature module needed the same parse. A
  new module keeps the path-resolution / JSON-parse logic in one
  place; either consumer can be swapped independently.
- **`__init__` reads the heaters, not just `on_load`.** The
  registry calls `_resolve_settings_model(instance)` before
  `on_load`, so the seeded `sensor_colors` must be available at
  construction time. `on_load` re-reads the list to pick up any
  in-process re-deployment (rare in practice — most operators
  restart the backend between deploys).
- **`reseed_from_hardware_json()` helper on the mock.** Tests
  that monkey-patch the active directory after the mock is loaded
  need a deterministic way to force a re-read. The function is
  idempotent and called once at module import for production.
- **`set_temperature` still creates a sensor on the fly.** The
  router-level `POST /sensors/{name}/target` path can target a
  sensor that wasn't seeded by `hardware.json` (e.g. an operator
  adds a chamber heater at runtime). The mock's existing
  `set_temperature` command already creates the entry on demand;
  behaviour is unchanged.
- **Deterministic colour seeding is the documented trade-off.**
  `bed=red`, `chamber=blue` after sorting. The operator can
  override any colour via the Settings panel and the override
  persists via `SettingsStore` merge semantics.
- **`#A855F7` (purple) stays as the frontend's "unknown sensor"
  fallback** so any sensor the backend introduces after the
  operator's last PUT still renders.

### Testing Verification (Issue #97)

- [x] Ran local test suite / build checks
- [x] 321 backend tests pass (`python -m pytest backend/tests -v`)
- [x] 98 frontend tests pass (`node --test "frontend/tests/**/*.mjs"`)
- [x] Frontend production build succeeds (`npm --prefix frontend run build`)
- [x] API client regenerates against the running backend
  (`npm --prefix frontend run generate-api`)

---

## Resolution Summary (Issue #99 — Toast service + structured compile errors)

Adds a frontend toast notification channel wired into the console store, and a backend duplicate-stepper-pin validation that surfaces a structured error envelope through the compile endpoint. The compile flow now toasts the operator the moment a profile fails validation.

### Files Modified (Issue #99)

- `backend/modules/machineconfig/parser.py`: Added `DuplicateStepperPinError` class, `kind`/`line`/`to_dict()` on the `ConfigValidationError` family, and the post-parse `_validate_stepper_pins` walk that enforces the new rule.
- `backend/modules/machineconfig/router.py`: Added a module-owned `register_exception_handlers(app)` helper plus a `ConfigValidationError` exception handler that returns the structured `{"error": {section, key, line, message, kind}}` envelope; reordered the compile endpoint's `try/except` so `ConfigValidationError` flows through the handler (it inherits from `ValueError`, which would otherwise swallow the structured response).
- `backend/modules/machineconfig/module.py`: Calls `register_exception_handlers(ctx.app)` from `on_load` so the handler is registered as soon as the FastAPI app is available.
- `backend/core/protocols.py` + `backend/core/module_registry.py`: Added `app: Optional[FastAPI]` to `ModuleContext` and pass the live app reference at mount time.
- `frontend/src/core/toast.js`: New Pinia store exposing `useToast()` with `success` / `info` / `warn` / `error`; auto-dismiss 5 s for success/info, persistent for warn/error; `durationMs` override supported; colour palette exported as `TOAST_TYPE_STYLES`.
- `frontend/src/components/ToastContainer.vue`: New `<ToastContainer>` component, fixed top-right, Tailwind palette consistent with `bg-gray-800` / `border-gray-700`. Owns auto-dismiss timers and `onBeforeUnmount` cleanup so HMR cannot leak callbacks.
- `frontend/src/App.vue`: Mounts `<ToastContainer />` alongside the existing router-view shell.
- `frontend/src/stores/console.js`: `error` / `info` / `warning` / `debug` / `success` now accept an optional `opts: { popup?: boolean, title?: string, durationMs?: number }`; default `popup=false` keeps every existing call site working unchanged. The toast channel is reached via a dynamic import to avoid the cross-store Pinia ordering trap documented in `.agent/LESSONS_LEARNED.md` § 2.4.
- `frontend/src/modules/machineconfig/store.js`: Updated `describeError` to read the new structured error envelope first (then the legacy `detail` string and finally `error.message`); the `compile` action now invokes `console.error(message, { popup: true, title: 'Compile failed' })` so the operator sees the failure without hunting in the console panel.
- `backend/tests/test_machineconfig_parser.py`: +6 tests — four per-pin-key (`step_pin` / `dir_pin` / `enable_pin` / `endstop_pin`) duplicates, plus a `ConfigValidationError` subclass check and a regression guard for legitimate multi-motor Y.
- `backend/tests/test_machineconfig_module.py`: +1 integration test using the issue's example config — `[stepper_x]` / `[stepper_y]` / `[stepper_z]` sharing `PG0` / `PG1` / `!PF15` produces a 400 response with the documented `{section, key, line, message, kind}` envelope.
- `frontend/tests/test-console-features.mjs`: +5 tests — three toast-store contract tests (method surface, auto-dismiss vs. persistence, palette / container wiring) and two console-store popup tests (forwarding to the toast layer, backward-compatible default). Existing `debug(text)` regex loosened to `debug\s*\(\s*text` so the new optional `opts` parameter does not break the static-structural contract.

### Architectural Decisions (Issue #99)

- **Module-owned exception handler, not a global registration.** The `ConfigValidationError` family belongs to the machineconfig parser, so the handler lives in `modules/machineconfig/router.py` and is registered from `on_load`. The legacy flat routers stay untouched.
- **`ModuleContext.app` is the wiring channel.** Adding `app: Optional[FastAPI]` to the dataclass is the smallest possible contract change — it preserves the existing `module_id` / `event_bus` / `settings` / `extras` fields and stays optional so the legacy test-only `isolated_machine_config` fixture (which never passes an app) still works.
- **Dynamic import in `console.js`.** Importing the toast store at module-init time would pull it into the console's evaluation cycle; the dynamic import inside `_emitToast` keeps the dependency one-way and lets the console still boot when the toast layer is absent (e.g. tests that mock Pinia).
- **`ConfigValidationError` is a `ValueError`.** The compile endpoint's existing `except ValueError` clause now has an explicit `except ConfigValidationError` ahead of it — reordering the existing branches would silently swallow the new structured response. The contract is documented inline so a future refactor cannot regress it.
- **Static-structural frontend tests.** Pinia is not drivable from bare `node --test` (see `.agent/LESSONS_LEARNED.md` § 5.2); the new toast/popup tests assert on the contract surface via regex. Dynamic regressions are caught by the Vite build step in CI.

### Testing Verification (Issue #99)

- [x] Ran local test suite / build checks
- Backend: `python -m compileall -q backend && python -m pytest backend/tests` → 324 passed (including 4 new parser tests for the duplicate-pin rule, 1 regression guard, and 1 compile-endpoint integration test using the user's example config).
- Frontend: `npm --prefix frontend run build` → ✓ built.
- Frontend: `node --test frontend/tests/**/*.mjs` → 103 passed (5 new tests for toast composable + console-store popup option).
- API codegen: `node frontend/scripts/generate-api.mjs` against the live backend → schema regenerated, no breakage.
