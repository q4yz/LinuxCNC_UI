### Resolution Summary

The temperature module's sensor list is now driven entirely by the
active `hardware.json` payload instead of a hard-coded
`extruder/bed/cpu` triple. The mock hardware layer, the temperature
module's settings defaults, the `HalCompiler` heater array, and the
frontend store all consume the same dynamic source of truth. Operators
who want a CPU gauge add a `cpu` heater to `machine.cfg`; the legacy
triple is dropped.

### Files Modified / Added

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

### Architectural Decisions

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

### Testing Verification

- [x] Ran local test suite / build checks
- [x] 321 backend tests pass (`python -m pytest backend/tests -v`)
- [x] 98 frontend tests pass (`node --test "frontend/tests/**/*.mjs"`)
- [x] Frontend production build succeeds (`npm --prefix frontend run build`)
- [x] API client regenerates against the running backend
  (`npm --prefix frontend run generate-api`)