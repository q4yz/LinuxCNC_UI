### Resolution Summary
Closes the post-#37 machine migration window by deleting the two transitional shims (`services/machineApi.js`, `stores/machine.js`) after migrating the only remaining consumer (`ConsolePanel.vue`) onto the canonical `ModulesMachineService.runMdiCommand`. No nullable-shell consumer is touched: every panel that needs machine state already routes through `stores/machine-compat`.

### Files Modified
- `frontend/src/components/ConsolePanel.vue`: dropped the legacy `import { machineApi } from '../services/machineApi'`, rewired `submitCommand` to call `ModulesMachineService.runMdiCommand({ command: cmd })` (the import for the generated service was already present), and kept `useMachineStore` from `stores/machine-compat` for the ESTOP guard.
- `frontend/src/core/modules/telemetry-bus.js`: refreshed two stale comments that still pointed at the deleted `stores/machine.js`; the bus contract itself is unchanged.
- `frontend/tests/test-machine-null.mjs`: replaced the obsolete "legacy shim re-exports `useMachineStore`" assertion with a positive-removal check that both deleted shims are gone, and refreshed the file-header docstring to mention the new `machine-compat` migration path.

### Files Removed
- `frontend/src/services/machineApi.js`: the raw `fetch` wrapper for `/api/v1/modules/machine/mdi`. The generated `ModulesMachineService.runMdiCommand` is the canonical replacement and is already used by the machine store's MDI actions; no other code referenced this shim.
- `frontend/src/stores/machine.js`: the legacy re-export shim (`export { useMachineStore, useMachineRefs } from '../modules/machine/store.js'`). No production code imported from this path after the migration window — consumer components (`App.vue`, `DebugPanel.vue`, `GCodeViewer.vue`, `UpdateManager.vue`, `ConsolePanel.vue`) all go through `stores/machine-compat` so the nullable-shell invariant holds.

### Architectural Decisions
- **MDI migration path**: chose the canonical generated service (`ModulesMachineService.runMdiCommand`) over routing through a Pinia store action. The store's only MDI wrappers (`setPosition`, `setCoordinateSystem`) bake in G-code generation or coordinate-system logging that the generic console submit doesn't want; calling the generated service directly preserves identical user-visible behavior (same `/api/v1/modules/machine/mdi` payload) and removes one layer of indirection.
- **No `machine-compat` change**: `machine-compat.js` is the documented nullable-shell adapter that must remain so deleting `modules/machine/` keeps the dashboard buildable. Keeping it untouched (and not introducing a new direct `from '../modules/machine/store.js'` import in shell components) preserves that guarantee.
- **No comment-only removal of `services/apiClient.js`**: that file pre-dates this PR and is unrelated; left alone per the "one concern per PR" rule.

### Testing Verification
- [x] `node --test frontend/tests/*.mjs` — **71 pass / 3 fail pre-existing**; identical pass/fail count before and after this change. The 3 failing tests (`console store exposes the four canonical log levels`, `console store addDebug helper routes through addMessage`, `store builds the ModulesMachineService.jogAxis payload for continuous jogs`) reproduce on the unmodified `main` and are out of scope. My new subtest `legacy stores/machine.js shim is removed after migration window closes` passes.
- [x] `npm --prefix frontend run build` — succeeds (670 modules transformed). Pre-existing chunk-size and `INEFFECTIVE_DYNAMIC_IMPORT` warnings are unchanged.
- [x] `python3 -m compileall -q backend` — succeeds with no output (clean byte-compile).
- [x] Manual grep confirms no remaining references to `services/machineApi`, `stores/machine.js` (outside obsolete comment history), or the `legacyStoreShim` paths it pointed at.
