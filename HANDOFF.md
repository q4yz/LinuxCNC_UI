### Resolution Summary
Completed and hardened the machine-module migration for issue #37. The machine/state/jog surfaces remain registry-mounted, the 500 ms watchdog now shuts down through the correct lifecycle and exposes a testable stop seam, persisted jog settings drive the frontend, WebSocket reconnects are cleaned up, and physically removing the machine module leaves an inert, buildable shell.

### Files Modified
- `backend/main.py`: call `ModuleRegistry.shutdown()` during FastAPI teardown instead of the nonexistent `unload()` method.
- `backend/modules/machine/jog.py`: retain compatibility names for the migrated active-jog state.
- `backend/modules/machine/jog_watchdog.py`: expose the configured timeout and route expired-axis stops through a shared, testable safety dispatch.
- `backend/modules/machine/settings.py`: document the frontend-consumed jog defaults and clarify the E-STOP policy flag.
- `backend/modules/machine/README.md`: document temperature/program relocation, watchdog behavior, settings, and the verified nullable-module path.
- `frontend/src/modules/machine/store.js`: consume persisted jog velocity/keepalive settings, prevent reconnect-after-unload, preserve legacy update state, and register safely with compatibility consumers.
- `frontend/src/modules/machine/index.js`: register/unregister the real store with the module lifecycle.
- `frontend/src/modules/machine/components/JogControls.vue`: initialize from the configured jog velocity and stop all in-flight jogs unconditionally on unmount.
- `frontend/src/stores/machine-compat.js`: add an inert fallback store for shell consumers when the optional module is disabled or deleted.
- `frontend/src/services/machineApi.js`: keep the legacy console buildable when codegen omits the absent machine service.
- `frontend/src/{App.vue,main.js}` and legacy shell components: resolve the module store through the nullable compatibility adapter and boot the registry before component setup.
- `frontend/tests/test-{camera-null,machine-null,machine-store}.mjs`: align static contract checks with lazy panel resolution, current generated service names, settings-driven cadence, and reconnect cleanup.
- `MODULE_SYSTEM_EVALUATION.md`: record lifecycle, settings, generated-client, and nullable-consumer deviations.

### Architectural Decisions
- The module-owned Pinia store remains the only functional machine store. `machine-compat.js` delegates to it only after the frontend registry mounts `machine`; otherwise it exposes inert state/actions so there is no axis functionality and no missing-module import.
- The direct legacy re-export remains for mounted third-party consumers, while internal shell components use the nullable adapter. This preserves the migration path without defeating the physical-folder deletion guarantee.
- The console uses a small fetch-based MDI wrapper because a clean OpenAPI regeneration correctly omits `ModulesMachineService` when the backend machine module is removed.
- The watchdog keeps the historical 500 ms default and reads the persisted override once at startup. Its stop dispatcher supports both the migrated jog helper and a watchdog-local hardware test seam.

### Testing Verification
- [x] `python -m compileall -q backend`
- [x] `python -m pytest backend/tests` — 70 passed.
- [x] `node --test frontend/tests/*.mjs` — 45 passed.
- [x] `node frontend/scripts/check-store-ids.mjs` — passed.
- [x] `npm --prefix frontend run build` — production build passed.
- [x] Nullable backend smoke test — booted without `backend/modules/machine/`; only camera/program/temperature mounted and no machine routes were registered.
- [x] Nullable frontend smoke test — production build passed without both machine module folders and without the generated machine service.
- [ ] `.agent/TEST.md` dependency bootstrap could not complete verbatim in this image: `python3 -m venv .venv` reports missing system `ensurepip`, root `npm ci` has no root lockfile, and `npm --prefix frontend ci` reports the pre-existing lock mismatch `@emnapi/runtime@1.11.3`. Verification used the existing installed environment; compile, tests, lint, and production build all passed.
