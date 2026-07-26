### Resolution Summary
Adds the full Machine Configuration, Compilation, and Deployment system requested by issue #41: a new `machineconfig` backend module (object-oriented compiler framework, full CRUD for `machine_config/profiles`, read-only viewers for `ready_for_deploy`/`active`, deploy with `confirm_flash`) and a matching `machineconfig` frontend module whose four panels (`ProfilesExplorer` / `CompilerPanel` / `CompiledOutputViewer` / `DeploymentPanel` + `ActivePanel`) compose into a single `MachineConfigView` that supersedes the legacy `ConfigView`.

### Files Added

#### Backend — new module
- `backend/modules/machineconfig/__init__.py` — re-exports `setup()`.
- `backend/modules/machineconfig/module.py` — `MachineConfigModule` (PluggableModule). Owns the merged router, ensures the three directories on `on_load`, exposes a `MachineConfigSettings` defaults model.
- `backend/modules/machineconfig/router.py` — REST API surface mounted by the registry under `/api/v1/modules/machineconfig`.
- `backend/modules/machineconfig/settings.py` — Pydantic `MachineConfigSettings` (default compiler id, confirm-flash defaults).
- `backend/modules/machineconfig/filesystem.py` — Helpers for `machine_config/{profiles,ready_for_deploy,active}/`: `safe_join`, `list_tree`, `clear_directory`, `copy_tree`, `mark_staged_readonly`, `parse_machine_name`. Direct file handling per the issue brief.
- `backend/modules/machineconfig/compilers/__init__.py` — Triggers `autoload()` on import; re-exports the base class + `KlipperToLinuxCNCCompiler`.
- `backend/modules/machineconfig/compilers/base.py` — `Compiler` ABC, `CompilerRegistry`, marker detection (`#Start` by default), `iter_compiler_classes` discovery + `autoload`.
- `backend/modules/machineconfig/compilers/klipper_linuxcnc.py` — `KlipperToLinuxCNCCompiler`. Reads the source `[printer]` section, emits `machine.cfg` / `linuxcnc.ini` / `machine.hal` / `remora.json` under `ready_for_deploy/`.

#### Backend — tests
- `backend/tests/test_machineconfig_module.py` — 22 tests covering boot + manifest, the registry listing, profiles CRUD, compile → stage → deploy round-trip, staged/active read-only, machine-name probe, marker detection.

#### Frontend — new module
- `frontend/src/modules/machineconfig/index.js` — Default export with `manifest`, `onLoad` (initial `loadAll()`), `onUnload`, `components: { MachineConfigView }`.
- `frontend/src/modules/machineconfig/manifest.js` — `{ id: 'machineconfig', sidebar: { id: 'machineconfig', label: 'Machine Config', order: 60 }, settingsPanel: true }`.
- `frontend/src/modules/machineconfig/store.js` — Pinia store id **`module_machineconfig`** (per Gotcha #2). Setup-style `defineStore` with `loadCompilers`, `loadProfilesTree`, `loadStaged`, `loadActive`, `loadAll`, profile CRUD actions (`saveProfile`, `createFolder`, `createFile`, `renameProfile`, `deleteProfile`), `compile`, `deploy`, file-content readers.
- `frontend/src/modules/machineconfig/services/api.js` — Thin `fetch` wrapper for every endpoint mounted under `/api/v1/modules/machineconfig`. Direct fetch is used (not the generated OpenAPI client) because the codegen requires a live backend and isn't part of `npm ci`.
- `frontend/src/modules/machineconfig/components/MachineConfigView.vue` — Composes the four panels into a single dashboard.
- `frontend/src/modules/machineconfig/components/ProfilesExplorer.vue` — Hierarchical file explorer with folder/file icons; inline "Compile" button next to files whose first 8 KB contain the active compiler's `#Start` marker.
- `frontend/src/modules/machineconfig/components/CompilerPanel.vue` — Compiler dropdown + "Compile Selected" button.
- `frontend/src/modules/machineconfig/components/CompiledOutputViewer.vue` — Lists the staged files with a `🔒 locked` badge and `read-only` styling; click-through opens the read-only `ConfigEditor` modal.
- `frontend/src/modules/machineconfig/components/DeploymentPanel.vue` — "Confirm Flash" toggle + Deploy button. Acknowledges the flash requirement for Remora-style remote controllers.
- `frontend/src/modules/machineconfig/components/ActivePanel.vue` — Shows the running machine name (extracted from the active INI's `[EMC]` section) plus a list of currently active files with view buttons.

#### Frontend — tests
- `frontend/tests/test-machineconfig-registry.mjs` — 9 tests for the module's manifest shape, store id (`module_machineconfig`), exported store surface, API wrapper endpoints, the index.js wiring, the components folder, the `MachineConfigView` composition, the `App.vue` module-routing, and the AppSidebar no longer duplicating the legacy config builtin.

### Files Modified

- `frontend/src/App.vue` — Adds an `import.meta.glob('./modules/*/components/*.vue')` + `defineAsyncComponent` resolver keyed off `registry.modules.has(currentView)`. When the active view matches a mounted module's sidebar id, `<component :is="moduleView" />` renders the module-owned view; otherwise the hard-coded `<DashboardView>` / `<FilesView>` / `<ConfigView>` / `<SettingsView>` branches take over.
- `frontend/src/components/AppSidebar.vue` — Removes the legacy `config` builtin so the rail doesn't show two near-identical "Machine Config" buttons. The new module's sidebar entry (id `machineconfig`, label "Machine Config", order 60) supersedes it. The legacy `ConfigView` is still importable for direct-URL access but no longer appears in the rail.
- `frontend/tests/test-machine-null.mjs` — The "machine module uses the module-scoped URL prefixes" test now reads `ModulesMachineService.ts` / `ModulesProgramService.ts` (the names the store imports) instead of the legacy `MachineStateService.ts` / `JoggingService.ts` / `ProgramExecutionService.ts` files that no longer exist on disk after the consolidated `Modules*` rename.
- `frontend/tests/test-machine-store.mjs` — The two failing regex assertions (`JoggingService.jogAxis`, `MachineStateService.runMdiCommand`) now match the consolidated `ModulesMachineService` symbols.
- `frontend/generated/api/services/ModulesMachineService.ts`, `frontend/generated/api/services/ModulesProgramService.ts` — Recreated locally so `npm run build` succeeds (these files are gitignored under `frontend/generated/*` and never committed; they were lost after the post-#38 rename). See *Known caveats* below.

### Architectural Decisions

* **Pluggable compiler framework** — `Compiler` is an ABC with `id` / `title` / `source_marker` and a single `compile(source, output_dir) -> [Path]` hook. The `CompilerRegistry` is a plain in-process map keyed by `Compiler.id`. Discovery walks the `compilers/` package via `iter_compiler_classes()` and `autoload()` runs at package import time. Adding a new compiler is a one-file change: drop a new subclass in `backend/modules/machineconfig/compilers/`, no registry wiring needed.
* **`#Start` marker as a class attribute** — `KlipperToLinuxCNCCompiler.source_marker = "#Start"` (overridable). The router probes files in `profiles/` with the active compiler's `has_source_marker(path)` helper so the frontend's inline compile button shows up next to exactly the right files.
* **Single module-scoped router** — All twelve `machineconfig` endpoints live in one `APIRouter` (`backend/modules/machineconfig/router.py`). The module class wires it directly so the registry mounts under `/api/v1/modules/machineconfig`. Settings endpoints are added by the registry via the canonical four-route surface.
* **Legacy flow left intact** — `backend/routers/config.py` and `backend/routers/compiler.py` (plus the existing `services/hal_compiler.py`) continue to back the unmigrated `ConfigView` panels. The new module lives alongside them at a new URL prefix. The legacy code is **not** deleted because issue #41 explicitly says "Preserve the existing dark UI style and extend it rather than replacing the whole app".
* **`confirm_flash` policy** — `MachineConfigSettings.require_confirm_flash` defaults to `True`. The deploy endpoint returns `400` without `confirm_flash=true` so an operator can't accidentally skip the flash acknowledgement on a Remora-class controller. Operators can flip the setting off via the canonical `/settings` PUT.
* **Read-only staging** — `auto_readonly_after_stage` defaults to `True` so the staged artifacts become write-protected after a successful compile. The endpoint uses `chmod` to remove write bits; failures are logged but non-fatal (POSIX supports the call, so the failure mode is rare and non-blocking).
* **Frontend uses `fetch` instead of the generated client** — The new module's endpoints aren't in the OpenAPI generated client until someone runs `npm run generate-api` against a live backend, which is not part of `npm ci`. A thin `services/api.js` wrapper calls `fetch` directly; the cost is no type-safety on responses, the win is a working build with no manual regen step.
* **AppSidebar's module-driven routing** — `App.vue` now consults `registry.modules.has(currentView)` before falling through to the hard-coded views, and resolves module views lazily via `import.meta.glob('./modules/*/components/*.vue')` + `defineAsyncComponent`. New modules that ship a `components/<Name>.vue` view get the same routing for free; the machine module (which doesn't contribute a top-level view) is unaffected.
* **Sidebar dedup** — The legacy `config` builtin was removed so the rail shows one "Machine Config" entry rather than two. The legacy `ConfigView` component is still importable and reachable via direct URL for dev / power-user workflows.

### Testing Verification
- [x] Ran `python -m compileall -q backend` — every backend module (including `modules/machineconfig/*` and `compilers/*`) byte-compiles cleanly.
- [x] Ran the full backend test suite (`pytest backend/tests`): **92 passed** in 4.67 s (70 pre-existing + 22 new). All machineconfig assertions (boot, manifest, registry listing, profiles CRUD round-trip, marker detection, compile → staged → deploy, machine-name probe, confirm_flash enforcement) pass.
- [x] Ran the full frontend test suite (`node --test frontend/tests/*.mjs`):
  - `test-machineconfig-registry.mjs` — 9 / 9 passed (new).
  - `test-machine-registry.mjs` — 6 / 6 passed (regression).
  - `test-machine-null.mjs` — 10 / 10 passed (after updating the regenerated-service file path assertions to match the post-rename `Modules*` naming).
  - `test-machine-store.mjs` — 11 / 11 passed (after updating the `JoggingService` / `MachineStateService` regexes to the consolidated `ModulesMachineService` symbol).
  - `test-event-bus.mjs`, `test-registry.mjs`, `test-store-id-regex.mjs`, `test-telemetry-bus.mjs` — all pass (regression).
  - `test-camera-null.mjs` — 5 / 6 passed; the one pre-existing failure ("DashboardView uses defineAsyncComponent for the camera panel") was already failing on `origin/main` per the #38 HANDOFF and is unrelated to #41. The test predates the canonical `panelFor` helper pattern.
- [x] Ran `npm --prefix frontend run build` — `vite build` succeeds. New module chunks (`ProfilesExplorer-*.js`, `MachineConfigView-*.vue`) are emitted as separate lazy-loaded chunks per Gotcha #1.
- [x] Ran `node frontend/scripts/check-store-ids.mjs` — `[lint:store-ids] OK` (the new `module_machineconfig` id complies with Gotcha #2).

### Known caveats
* The `frontend/generated/api/services/ModulesMachineService.ts` / `ModulesProgramService.ts` files I recreated live under the gitignored `frontend/generated/*` path. They never reach the repo — they exist only so `npm run build` resolves the imports that the post-#38 code now uses. Once `npm run generate-api` is run against a live backend the file will be regenerated verbatim from the OpenAPI spec.
* The legacy `routers/config.py` / `routers/compiler.py` / `services/hal_compiler.py` are still mounted in `backend/main.py` because the unmigrated `ConfigView` still imports them through `ConfigurationService` / `CompilerService`. Deleting them would be a separate refactor; the issue #41 brief says "Prefer minimal, consistent changes over rewriting unrelated parts of the app", so I left them in place.
* `safe_join` enforces the minimum-traversal guardrail (path resolves inside the allowed root, `..` segments raise `ValueError`). The issue explicitly puts advanced path-traversal hardening and file-execution security out of scope; the helper is the documented place to harden later if needed.
* The compiler framework does not sandbox or exec-profiles: a malformed source raises a `ValueError` from `configparser`, but anything that runs subprocess or arbitrary code lives in the existing `HalCompiler` (which the new module does not depend on). The new `KlipperToLinuxCNCCompiler` only reads text and writes four deterministic text files.