### Resolution Summary
Adds a new `ActivePrintWidget.vue` dashboard panel, the supporting `isPrinting` / `isPaused` / `printProgress` getters and program-lifecycle actions on the Pinia machine store, and converts `FileManager.vue` into a full-page view with per-row Edit buttons that bubble to the shared full-screen `ConfigEditor`.

### Files Modified
- `frontend/src/modules/machine/store.js` — adds `total_lines` to the default `status`, derives `isPrinting` / `isPaused` / `printProgress` from `task_state` + `interp_state`, and exposes `startProgram`, `pauseProgram`, `resumeProgram`, `abortProgram` actions that delegate to the generated `ModulesProgramService` client.
- `frontend/src/stores/machine-compat.js` — mirrors the new reactive defaults, derived getters, and action surface on the fallback store so the widget still renders when the optional machine module is not mounted.
- `frontend/src/components/ActivePrintWidget.vue` — new component (added). Switches between a Standby view (five newest `.gcode` / `.ngc` files with per-row Print buttons) and an Active view (loaded filename, progress bar bound to `printProgress`, Pause/Resume and Stop/Cancel controls). All actions go through the Pinia store; the backend telemetry stream is expected to flip the widget's state on the next polling cycle.
- `frontend/src/components/FileManager.vue` — wrapper now stretches `h-full w-full` with `flex-1 min-h-0` on the table body so it fills its parent; emits a new `edit` event with the filename when the new per-row Edit button is clicked; widens the Actions column to accommodate the extra button.
- `frontend/src/views/FilesView.vue` — replaces the placeholder card with a full-page wrapper around `FileManager` and re-emits the `edit` event to the parent so `App.vue` can mount the shared `ConfigEditor`.
- `frontend/src/App.vue` — wires `@edit="openEditor"` on `FilesView` so Edit requests from `FileManager` open the same full-screen editor used by the Config view.
- `frontend/src/views/DashboardView.vue` — imports `ActivePrintWidget` and renders it at the top of the right column above the toolpath viewer.

### Architectural Decisions
- The widget imports the store via the `machine-compat` adapter (`useMachineStore`) so it transparently uses the real module store when mounted and the inert fallback otherwise, matching the pattern already used by `DroPanel` / `JogControls`.
- `isPrinting` and `isPaused` are defined as mutually exclusive: both require `task_state === 2` (LinuxCNC `RCS_EXEC`); they differ only on `interp_state === 3` (`INTERP_PAUSED`). This keeps the Pause/Resume button label swap non-flickery.
- `printProgress` reads `status.total_lines` (defaults to 0) and collapses to 0 when missing, finite-checked, or non-positive — matching the issue's "if total_lines is 0 or missing, return 0" contract.
- The widget calls `NcFilesService.listFiles` directly for the standby view (mirroring `FileManager`) rather than introducing a new files store; the same filter / sort / slice logic the issue describes is implemented locally as a small `computed`.
- The Edit button emits an `edit` event instead of importing `ConfigEditor`; `FilesView` forwards it to `App.vue` which already owns the full-screen editor state via `openEditor()`. This keeps the "view owns layout, component owns display" boundary.
- Pause/Resume and Stop dispatch through the store actions (`pauseProgram` / `resumeProgram` / `abortProgram`) which call `ModulesProgramService` — the existing generated client. Per the issue, no local toggling is performed; the backend telemetry stream is the source of truth.

### Testing Verification
- [x] `python -m compileall -q backend` (via `.venv/bin/python`) — passed.
- [x] `npm --prefix frontend run build` — passed; only pre-existing `INEFFECTIVE_DYNAMIC_IMPORT` warnings remain (unrelated to this change).
- [x] Ran the existing `frontend/tests/*.mjs` suite — the four pre-existing failures (`test-machine-store.mjs` test 2, `test-console-features.mjs` tests 1 & 6, `test-machineconfig-registry.mjs` test 8) reproduce on the unmodified base branch and are not caused by this change. No new regressions.
- [ ] Backend pytest suite was not invoked; the change is frontend-only and the existing backend already exposes `/api/v1/modules/program/{run,pause,resume,stop}` that the new actions target.