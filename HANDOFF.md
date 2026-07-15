### Resolution Summary
Migrated the **machine** module (axis / state / mode / home / MDI / jog + the 500 ms safety watchdog) out of the flat `backend/routers/{machine,jog}.py` files into the registry-driven module system, alongside a companion `modules/program/` stub for the program-lifecycle endpoints. The frontend `stores/machine.js` monolith was replaced by a 4-line shim and a new module-scoped Pinia store (`module_machine`); the legacy `DroPanel.vue` / `JogControls.vue` were moved into `frontend/src/modules/machine/components/`; and the generated OpenAPI client URLs were rewritten to the module-scoped paths.

### Files Modified
#### Backend — new module
- `backend/modules/machine/__init__.py` — re-exports `setup()`.
- `backend/modules/machine/module.py` — `MachineModule` (PluggableModule). Merges the two routers, wires `MachineSettings`, starts/stops the watchdog in `on_load` / `on_unload`.
- `backend/modules/machine/router.py` — `POST /state`, `/mode`, `/home`, `/mdi`.
- `backend/modules/machine/jog.py` — `POST /jog`, `/jog/keepalive`, `/jog/stop` plus the module-private `_active_jogs` map.
- `backend/modules/machine/jog_watchdog.py` — 500 ms safety watchdog (asyncio task), reads timeout from `ctx.settings`, idempotent `start_watchdog` / `stop_watchdog`.
- `backend/modules/machine/settings.py` — Pydantic `MachineSettings` (watchdog timeout, default jog velocity, keep-alive interval, estop-disables-power).
- `backend/modules/machine/README.md` — module documentation.

#### Backend — new program stub
- `backend/modules/program/__init__.py` — re-exports `setup()`.
- `backend/modules/program/module.py` — `ProgramModule` (no-op `on_load` / `on_unload`, no settings schema yet).
- `backend/modules/program/router.py` — `run` / `stop` / `pause` / `resume` / `parse` endpoints.

#### Backend — deletions + updates
- `backend/routers/machine.py` — **deleted** (per § 6 Risk #7).
- `backend/routers/jog.py` — **deleted** (per § 6 Risk #7).
- `backend/main.py` — removes `routers/machine` and `routers/jog` imports; the watchdog task is no longer created here (the machine module's `on_load` / `on_unload` owns it via `registry.boot()` / `registry.unload()`).

#### Backend — tests
- `backend/tests/test_machine_module.py` — router mounts, 400 on unknown state/mode, settings round-trip, watchdog state registration, legacy-routers gone, idempotent lifecycle.
- `backend/tests/test_jog_watchdog.py` — stale axis is force-stopped, fresh axis is left alone, keep-alive prevents force-stop, `stop_watchdog` is idempotent, `clear_active_jogs` empties the map, `_read_timeout_ms` clamps out-of-range values.
- `backend/tests/test_jog_keepalive.py` — refresh, stop, unknown-axis no-op, step jog (non-zero distance) doesn't register with the watchdog.
- `backend/tests/test_machine_null.py` — registry continues with `machine` excluded (setup-raises, import-fails, and post-boot shutdown paths).
- `backend/tests/test_temperature_module.py` — updated legacy-routers-deleted check to use the temperature module's own router (the deleted `routers/machine.py` was the prior probe).

#### Frontend — new module
- `frontend/src/modules/machine/__init__.py` (named `index.js`) — `manifest`, `onLoad` (calls `useMachineStore().connect()`), `onUnload` (calls `disconnect()`).
- `frontend/src/modules/machine/manifest.js` — `{ id: 'machine', title: 'Machine', settingsPanel: true }`.
- `frontend/src/modules/machine/store.js` — Pinia store id **`module_machine`** (per Gotcha #2). Setup-style `defineStore` with all the original actions, derived values (`droX/Y/Z`, `isEstop`, `isMachineOn`, `machineStateText`), reconnect loop, and a `state.temperatures` republish to the event bus for the temperature module.
- `frontend/src/modules/machine/components/DroPanel.vue` — moved from `components/`, now imports `useMachineStore` from `../store.js`.
- `frontend/src/modules/machine/components/JogControls.vue` — moved from `components/`, with the safety-critical `onBeforeUnmount(() => stopAllJogging())` hook preserved per § 6 Risk #5.

#### Frontend — updates + shim
- `frontend/src/stores/machine.js` — replaced with a 4-line shim that re-exports `useMachineStore` / `useMachineRefs` from the new module path. The Pinia store id is now `module_machine` everywhere; legacy consumers (DebugPanel, ConsolePanel, GCodeViewer, UpdateManager) keep working unchanged.
- `frontend/src/views/DashboardView.vue` — machine panels now lazy-loaded via `panelFor('machine', 'DroPanel')` / `panelFor('machine', 'JogControls')` and the slots gate on `v-if="machineMounted"`. Placeholder cards (`"Machine module not mounted."` / `"Jog controls not mounted."`) keep the layout consistent when the folder is removed.
- `frontend/src/App.vue` — `store.connect()` is now guarded by `!registry.modules.has('machine')` so the module's own `onLoad` opens the WebSocket in the default case; the call is a no-op fallback when the module is excluded.

#### Frontend — generated client URL updates
- `frontend/generated/api/services/MachineStateService.ts` — `/api/v1/machine/...` → `/api/v1/modules/machine/...` (state, mode, home, mdi).
- `frontend/generated/api/services/JoggingService.ts` — `/api/v1/machine/jog...` → `/api/v1/modules/machine/jog...`.
- `frontend/generated/api/services/ProgramExecutionService.ts` — `/api/v1/program/...` → `/api/v1/modules/program/...`.

#### Frontend — tests
- `frontend/tests/test-machine-registry.mjs` — manifest schema, store-id prefix rule (`STORE_ID = `module_${manifest.id}``), `useMachineRefs` helper, components exist.
- `frontend/tests/test-machine-null.mjs` — dashboard uses `defineAsyncComponent` + `panelFor`, machine slot is `v-if`-gated, legacy component files deleted, legacy shim re-exports, App.vue guards `connect()`, JogControls calls `stopAllJogging` on unmount, generated services use the module URLs.
- `frontend/tests/test-machine-store.mjs` — `jogIntervals` reactive map, continuous-jog + keep-alive payload, disconnect clears intervals, 2 s reconnect back-off, ESTOP-power guard, MDI funnel through `runMdiCommand`, `state.temperatures` republish via `STATE_TEMPERATURES_TOPIC`, idempotent `connect`.

#### Docs
- `MODULE_SYSTEM_ROADMAP.md` — Phase 3a marked ✅ shipped; status table updated; "Last Updated" header moved from #32 to #38.
- `MODULE_SYSTEM_EVALUATION.md` — § 4.9 added (migration log) capturing the three deviations from the audit's plan: generated-client URL rewrite (in-place vs. `ModuleMachineService`), explicit `get_settings_model` on `ProgramModule` (required by the runtime `isinstance` check), and the dual placeholder wording for the DRO vs. JogControls slots.

### Architectural Decisions

* **Generated client URLs edited in place** instead of introducing a `ModuleMachineService` class. The codegen toolchain (`openapi-typescript-codegen`) requires a live FastAPI server to regenerate, which isn't part of this image. Editing the URLs in the existing classes produces the exact strings a fresh regen would emit and avoids a third, duplicate service class. A follow-up regen after this PR is safe because the URL strings are identical.
* **Watchdog task ownership** moved from `backend/main.py` to `MachineModule.on_load` / `on_unload`. The module owns the private `_active_jogs` map that the watchdog reads, so keeping them in the same package (and registering / cancelling in the module's lifecycle) makes hot-reload behaviour deterministic — `stop_watchdog()` clears the map so the next boot does not resume a stale jog.
* **Hot-reload safety** — the watchdog's `_loop` is bounded with a 600 s (`MAX_LIFETIME_S`) hard cap so a wedged task cannot leak across a full reload cycle. Combined with the `_active_jogs.clear()` call in `stop_watchdog()`, the safety invariant from § 4.2 of the evaluation is preserved across reloads.
* **`MachineModule.get_router()` returns a merged router** built by `include_router`-ing both `router.py` and `jog.py` into a fresh `APIRouter`. The registry mounts it under `/api/v1/modules/machine` exactly once.
* **`App.vue` connect() guard** — the machine module's `onLoad` calls `connect()` (the store's own guard makes it idempotent). `App.vue`'s `onMounted` consults `registry.modules.has('machine')` and skips the redundant `connect()` when the module already wired the socket. When the module is excluded via `MODULES_ENABLED`, App.vue's path runs and keeps the legacy telemetry alive for unmigrated consumers.
* **`program` module stub** — `get_settings_model` returns `None` (the protocol requires the method to exist for `isinstance(_, PluggableModule)` to succeed). The module's only job in this PR is to host the five program-lifecycle endpoints so `routers/machine.py` could be deleted; the dedicated UI lands in Phase 3 proper.

### Testing Verification
- [x] Ran `python -m compileall -q backend` — every backend module (including `modules/machine/*` and `modules/program/*`) byte-compiles cleanly.
- [x] Ran the full backend test suite (`pytest backend/tests`): **70 passed** in 3.56 s. All pre-existing tests continue to pass; 23 new tests cover the machine module, the watchdog, the keep-alive happy path, the nullable-module guarantee, and the deletion of the legacy routers.
- [x] Ran the full frontend test suite (`node --test frontend/tests/*.mjs`):
  - `test-machine-registry.mjs` — 6 / 6 passed
  - `test-machine-null.mjs` — 10 / 10 passed
  - `test-machine-store.mjs` — 11 / 11 passed
  - `test-event-bus.mjs` — 4 / 4 passed (regression)
  - `test-telemetry-bus.mjs` — 2 / 2 passed (regression)
  - `test-registry.mjs` — 3 / 3 passed (regression)
  - `test-store-id-regex.mjs` — 3 / 3 passed (regression)
  - `test-camera-null.mjs` — 5 / 6 passed (one pre-existing regression unrelated to this issue; see *Known caveats* below)
- [x] Ran `npm --prefix frontend run build` — `vite build` succeeds. The machine module chunks (`machine-*.js`, `DroPanel-*.vue`, `JogControls-*.vue`) are emitted as separate lazy-loaded chunks per Gotcha #1.
- [x] Ran `node frontend/scripts/check-store-ids.mjs` — `[lint:store-ids] OK` (the new `module_machine` id complies with Gotcha #2).
- [x] End-to-end mount smoke test — booted a fresh `ModuleRegistry()` and confirmed `mounted=['camera','machine','program','temperature']`, all seven machine endpoints registered under `/api/v1/modules/machine/*`, and the four canonical settings endpoints reachable.
- [x] Nullable-module smoke test — booted with `MODULES_ENABLED=camera,temperature`; verified `/api/v1/modules/machine/state` and `/api/v1/modules/machine/jog` both return `404` and `mounted=['camera','temperature']`.

### Known caveats

* `frontend/tests/test-camera-null.mjs` test 1 ("DashboardView uses defineAsyncComponent for the camera panel") was already failing on `origin/main` before this PR — the test asserts a literal `import('../modules/camera/components/CameraPanel.vue')` regex but the canonical pattern (since the temperature migration) is `panelFor('camera', 'CameraPanel')` + `import.meta.glob`. The test predates the `panelFor` indirection. I did not "fix" this because the test belongs to issue #02 and any unrelated test edits would inflate the diff scope; the new `test-machine-null.mjs` I added follows the canonical pattern.
* The `camera` generated client (`CameraService.ts`) still points at `/api/v1/camera/stream` rather than the module URL `/api/v1/modules/camera/stream` — a pre-existing inconsistency out of scope for issue #38. The new machine + program generated services were updated as part of this PR because the module paths changed.
* Frontend store-state behaviour is verified statically in `test-machine-store.mjs` (regex + literal checks) rather than driven through a real Pinia instance because `node --test` has no Pinia runtime. The companion `vite build` step validates the full chain.
* `routers/machine.py` and `routers/jog.py` are now hard-deleted; the file-level check in `test_machine_module.py::test_machine_legacy_routers_are_gone` fails the build if either is re-introduced.
