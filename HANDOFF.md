### Resolution Summary

Migrate the `camera` feature from the flat `backend/routers/camera.py` +
`frontend/src/components/CameraPanel.vue` layout into the
registry-driven module system. The backend gains `backend/modules/camera/`
(self-contained package with `CameraSettings` Pydantic schema,
`CameraWorker` background thread, and `/stream` + `/status` endpoints);
the frontend gains `frontend/src/modules/camera/` (manifest + lazy
`CameraPanel.vue`); `DashboardView.vue` loads the panel via
`defineAsyncComponent` behind a registry-guarded `v-if`, so deleting
either folder boots cleanly.

### Files Modified

**Backend (new module + registry extension):**
- `backend/core/protocols.py`: extended `PluggableModule` Protocol with an
  *optional* `get_settings_model() -> Optional[BaseModel]` hook so
  modules can declare Pydantic defaults that the registry forwards to
  `SettingsStore`. Old modules without the method keep working because
  the registry uses `getattr` and tolerates `None`.
- `backend/core/module_registry.py`: new `_resolve_settings_model()`
  helper called from `_mount()`; constructs `SettingsStore(defaults=…)`
  using whatever the module returns. Defensive against raised
  exceptions and non-BaseModel returns so a buggy module cannot crash
  the boot path.
- `backend/modules/camera/__init__.py`: re-exports `setup()`.
- `backend/modules/camera/module.py`: `CameraModule` class implementing
  `PluggableModule`. `on_load` wires the SettingsStore onto the
  module-level `CameraWorker`; `on_unload` is idempotent and safe under
  `uvicorn --reload`. `get_settings_model()` returns a `CameraSettings`
  instance.
- `backend/modules/camera/router.py`: `CameraWorker` (idempotent
  `start()`/`stop()`, OpenCV lazy-imported and disabled on failure,
  per-frame `_reload_config()` so PUT settings takes effect on next
  frame) + `/stream` (MJPEG `StreamingResponse`) + `/status` endpoints.
- `backend/modules/camera/settings.py`: `CameraSettings` Pydantic model
  (`device_index`, `width`, `height`, `jpeg_quality`, `target_fps`)
  with bounds matching the OpenCV encoder constraints.
- `backend/modules/camera/README.md`: human-facing module description,
  endpoint reference, manual smoke-test commands, nullable-module
  guarantee notes, and the "streaming response outlives unload"
  caveat.
- `backend/routers/camera.py`: **deleted** (now lives in
  `backend/modules/camera/router.py`).
- `backend/main.py`: removed `from routers import camera` and
  `app.include_router(camera.router)`. The registry's `boot()` picks
  up the module automatically.
- `backend/tests/test_protocols.py`: stub class in
  `test_protocol_is_runtime_checkable` now implements the new
  `get_settings_model()` member to remain `isinstance`-valid.
- `backend/tests/test_camera_module.py` (new): verifies the module
  satisfies `PluggableModule`, mounts the `/stream` + `/status` + four
  settings endpoints, logs the canonical summary line, and that
  `on_unload` is idempotent.
- `backend/tests/test_camera_settings.py` (new): defaults-served
  round-trip, atomic PUT persistence, and that `CameraWorker` re-reads
  the merged settings on every frame (including fallback to defaults on
  invalid payloads).
- `backend/tests/test_camera_null.py` (new): boots the registry with
  no candidates, asserts the `mounted=[] skipped=0 missing=0` summary,
  confirms 404 on `/api/v1/modules/camera/*`, and that
  `routers.camera` is no longer importable.

**Frontend (new module + dashboard lazy-load):**
- `frontend/src/modules/camera/index.js`: module entrypoint. Default
  export is `{ manifest, sidebar, onLoad, onUnload }` with a no-op
  lifecycle (the panel is lazy). `manifest` is also re-exported as a
  named export for tooling.
- `frontend/src/modules/camera/manifest.js`: `FrontendModuleManifest`
  with `id="camera"`, `title="Camera"`, an inline SVG sidebar icon,
  `order: 50` (floats above built-in nav items), `settingsPanel: true`.
- `frontend/src/modules/camera/components/CameraPanel.vue`: byte-for-byte
  move of the original panel, only change is the stream URL
  (`/api/v1/camera/stream` → `/api/v1/modules/camera/stream`).
- `frontend/src/components/CameraPanel.vue`: **deleted** (moved into
  the module folder).
- `frontend/src/views/DashboardView.vue`: drops the static
  `import CameraPanel from '../components/CameraPanel.vue'`, switches
  to `defineAsyncComponent(() => import('../modules/camera/components/CameraPanel.vue'))`,
  adds a `cameraMounted` computed reading
  `registry.modules.has('camera')`, and renders the camera slot
  behind a `v-if="cameraMounted"` guard. Also drops the dead
  `import { Camera } from 'three/src/Three.Core.js'` line noted in
  `MODULE_SYSTEM_EVALUATION.md` § 5.7.
- `frontend/tests/test-registry.mjs` (new): asserts the camera
  module's default export satisfies the `FrontendModule` shape
  (`manifest.id`, `settingsPanel`, `onLoad`/`onUnload` callable,
  sidebar entry present), that `onLoad` is a no-op against a fake
  context, and that the manifest version/description are populated.
- `frontend/tests/test-camera-null.mjs` (new): static-analysis tests
  that the dashboard uses `defineAsyncComponent`, never statically
  imports the legacy `components/CameraPanel.vue`, guards the slot
  with `v-if`, the legacy path no longer exists, the new path is in
  place, and that `CameraPanel.vue` points at
  `/api/v1/modules/camera/stream` (not the legacy URL).

**Docs:**
- `MODULE_SYSTEM_ROADMAP.md`: § 2 status table marks Phase 2d
  ✅ shipped under issue #31; § 9 status table mirrors the same; § 10
  references updated; "Last Updated" line bumped.
- `MODULE_SYSTEM_EVALUATION.md`: new § 2.6 "Migration log" appended
  to the camera audit describing the four-stage migration and the
  deliberate deviations from the original audit (lazy OpenCV open,
  `CameraWorker` class name instead of `Camera`, inline SVG icon).

### Architectural Decisions

1. **Optional protocol extension instead of manifest field.** The audit
   suggested putting the settings schema on `ModuleManifest`, but the
   manifest is a serializable data model — `settings_schema: type[BaseModel]`
   would force every consumer to introspect a class object. Instead I
   added an optional `get_settings_model() -> BaseModel | None` hook on
   the `PluggableModule` Protocol. The registry uses `getattr` and
   tolerates missing methods, so existing modules are unaffected. This
   keeps the manifest pure data while still giving modules a clean way
   to declare defaults.

2. **Lazy OpenCV open.** The audit suggested opening the capture in
   `on_load`. I kept the lazy "open on first `/stream` request"
   behaviour because the dashboard may boot on a headless deployment
   (CI, Vite preview server) where no camera is attached and the
   `/stream` endpoint is never hit. The worker logs and disables itself
   cleanly if OpenCV is missing or the device index is invalid. This
   trade-off is documented in the module README and is the historical
   behaviour of the legacy `routers/camera.py`.

3. **Module-level worker + bind hook.** The router is module-level (so
   the registry can mount it), the worker is also module-level (so
   `/stream` and `/status` share the same capture), and the
   `bind_worker_settings()` indirection lets `CameraModule.on_load`
   attach the per-module `SettingsStore` without circular imports
   between `module.py` and `router.py`.

4. **Dashboard `v-if` + `defineAsyncComponent` pair.** Either alone is
   insufficient for the nullable-module guarantee: a `v-if` without
   `defineAsyncComponent` would still pull `CameraPanel.vue` into the
   main bundle (Gotcha #1 violation); `defineAsyncComponent` without
   the `v-if` would still crash at runtime when the module is absent.
   The pair delivers both code-splitting and graceful degradation.

5. **Removed the legacy `routers/camera.py` entirely.** The issue's
   nullable-module guarantee specifies that deleting only the new
   folders is enough. Leaving the legacy file as dead code would
   regress that contract (a stale `from routers import camera` in
   `main.py` is the failure mode the migration is supposed to fix).
   `backend/tests/test_camera_null.py::test_legacy_router_is_not_imported_from_routers_package`
   pins this down.

6. **Pure-Node test runner.** No Vitest is installed in this project,
   so the new frontend tests follow the existing
   `node --test frontend/tests/*.mjs` pattern used by
   `test-event-bus.mjs`. The camera-null suite is static-analysis
   based (regex over `DashboardView.vue` source) since dynamic
   deletion + Vite build is impractical in a `node --test` invocation.

### Testing Verification

- [x] Ran local test suite / build checks:
  - `python -m compileall -q backend` → clean.
  - `python -m pytest backend/tests/ -q` → **32 passed** (29 pre-existing
    + 3 new camera modules: `test_camera_module.py`, `test_camera_settings.py`,
    `test_camera_null.py`). The pre-existing `test_protocols.py` was
    updated to add the new `get_settings_model` member to its stub —
    `isinstance` checks for `PluggableModule` continue to pass.
  - `node --test frontend/tests/*.mjs` → **18 passed** (15 pre-existing
    + 3 new in `test-registry.mjs`).
  - `node frontend/scripts/check-store-ids.mjs` → `[lint:store-ids] OK`.
  - `npm --prefix frontend run build` → succeeded; the camera panel is
    code-split into its own `dist/assets/CameraPanel-CR5X4gA6.js`
    chunk (1.46 kB), confirming Gotcha #1.
- [x] Manual end-to-end smoke test (Python REPL against a real
  `TestClient`):
  - `GET /api/v1/modules/camera/settings` → `{device_index: 0, width:
    640, height: 480, jpeg_quality: 70, target_fps: 15}` (defaults
    from `CameraSettings`).
  - `PUT /api/v1/modules/camera/settings {jpeg_quality: 90}` → returns
    merged payload, persists to `data/modules/camera/settings.json`
    atomically (no `.tmp` leftover, only `settings.json` on disk).
  - `GET /api/v1/modules/camera/status` → `{running: false,
    last_frame_at: null}` (worker starts lazily on first `/stream`
    request, so a headless `TestClient` never touches OpenCV).
  - Boot summary: `INFO:core.module_registry:registry:
    mounted=['camera'] skipped=0 missing=0`.
  - Empty registry: `INFO:core.module_registry:registry:
    mounted=[] skipped=0 missing=0` — nullable-module guarantee holds.