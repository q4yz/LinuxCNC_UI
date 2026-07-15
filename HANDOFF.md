### Resolution Summary
Implements issue #35 end-to-end: the temperature chart now renders a flowing 30-second curve (cubic interpolation + deterministic noise), the control box adds eye-icon visibility toggles + a global °C / K unit toggle, and every sensor's colour is shared between the chart and the control box via the module's settings store. Backend `TemperatureSettings` gains `unit` (Literal) and `sensor_colors` (Dict[str, str]) and drops the never-honoured `history_*` fields.

### Files Modified
- `backend/modules/temperature/settings.py`: add `unit` + `sensor_colors`; remove `history_window_seconds` / `history_poll_interval_ms`. Defaults seeded by the existing `get_settings_model()` factory.
- `backend/tests/test_temperature_module.py`: assert defaults match the new shape (`unit`, `sensor_colors`); drop stale `history_*` assertions.
- `backend/tests/test_temperature_settings.py`: rewrite defaults/round-trip tests around the new fields; add a test confirming the full sensor-colour map round-trips.
- `frontend/src/modules/temperature/store.js`: new reactive state (`unit`, `visibleSensors`, `sensorColors`); new actions (`setUnit`, `toggleSensorVisibility`, `setSensorColor`, `displayTemp`, `colorFor`); the polling cadence now drives a fixed 30 s window.
- `frontend/src/modules/temperature/components/TemperaturePanel.vue`: rewritten chart options — fixed 30 s × 1 Hz window, smoothstep interpolation, deterministic tick-index jitter, per-sensor colours, eye toggles, °C/K unit toggle, 2-decimal rounding, explicit ECharts `grid` margins.
- `frontend/src/modules/temperature/index.js`: export the new `TemperatureSettingsPanel` and register it as `settingsPanel` on the module record.
- `frontend/src/core/modules/protocols.js`: document the new optional `settingsPanel` field on the `FrontendModule` typedef.
- `frontend/src/core/modules/registry.js`: stash `instance.settingsPanel` on each module record; return it from `settingsPanels()` so the Settings view can render it.
- `frontend/src/views/SettingsView.vue`: render module-supplied settings-panel components via `<component :is="panel">`; fall back to the legacy placeholder when the module hasn't shipped one yet.

### Files Added
- `frontend/src/modules/temperature/components/TemperatureSettingsPanel.vue`: Settings-tab content for the temperature module — global unit dropdown + per-sensor colour `<input type="color">` rows. Both mutations persist via the canonical `PUT .../settings/{key}` endpoints.

### Architectural Decisions
- **History window locked to 30 s.** Per the issue brief we removed `history_window_seconds` / `history_poll_interval_ms` from `TemperatureSettings` because they were never honoured by the chart anyway. The frontend now hard-codes `WINDOW_SECONDS = 30` and the rolling-window prune reads from that constant; the store still exposes a `windowMs` ref for future-proofing but no longer derives it from the backend.
- **Settings-store merge semantics left as-is.** `SettingsStore._merge_defaults` does a shallow merge, so a partial `{"sensor_colors": {"extruder": "#000000"}}` payload fully replaces the default palette at that top-level key. The frontend always sends the full merged map from its in-memory store, so visual identity is preserved end-to-end; the test suite reflects that nuance (one test for partial-PUT semantics, one for the full-map round-trip the frontend actually emits).
- **Settings panel opt-in via the module record.** Adding the `settingsPanel` field on the `FrontendModule` contract is a strictly additive change. Modules that haven't shipped a panel (only `temperature` has so far) keep rendering the legacy placeholder; this preserves backward compatibility without forcing every existing module to update its `index.js`.
- **Display-only unit conversion.** Per the brief the backend never converts; `store.displayTemp(celsius)` and the chart's `valueFormatter` handle the K = °C + 273.15 hop. The interpolated series itself stays in Celsius so toggling the unit is a cheap re-render, not a re-interpolation.
- **Deterministic per-tick jitter.** The GLSL `sin(i * 12.9898) * 43758.5453` hash is keyed on the integer tick index — not the absolute timestamp — so the chart's pixels are stable between re-renders and the line never flickers. Catmull–Rom was deliberately left for a follow-up issue (it's noted as out-of-scope).
- **Per-sensor chart series are still rendered as smooth-on-every-segment.** ECharts `smooth: true` on a 30-element series reads as a curve rather than a staircase; the issue's "smooth interpolation with noise" goal is satisfied without overshooting into per-segment Catmull–Rom territory.

### Testing Verification
- [x] Ran local test suite / build checks (per `.agent/TEST.md`).
- [x] `python -m compileall -q backend` — no errors.
- [x] `python -m pytest backend/tests/` — 47/47 passed (12/12 touch the temperature module; the other 35 cover the camera module, registry, settings store, event bus, and protocols).
- [x] `npm --prefix frontend run build` — bundle built; new `TemperatureSettingsPanel` chunk appears at `dist/assets/TemperatureSettingsPanel-*.js` and the temperature module chunk reflects the rewritten panel.
- [x] `node frontend/scripts/check-store-ids.mjs` — passes (`module_temperature` still matches `^module_[a-z][a-z0-9_]+$`).
