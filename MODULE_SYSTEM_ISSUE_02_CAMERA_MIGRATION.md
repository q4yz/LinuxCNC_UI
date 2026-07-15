# Issue #2 — Migrate `camera` into the module system

> **Status:** not started
> **Tracks:** [`MODULE_SYSTEM_ROADMAP.md`](MODULE_SYSTEM_ROADMAP.md) Phase 2d
> **Companion:** [`MODULE_SYSTEM_EVALUATION.md`](MODULE_SYSTEM_EVALUATION.md) § 2
> **Scope:** the camera feature only — backend router, frontend panel,
> and the new settings schema.
> **Risk class:** low — see § 2 of the evaluation.

---

## 1. Problem

The camera feature currently lives as a flat file
`backend/routers/camera.py` + a flat `frontend/src/components/CameraPanel.vue`.
Both are imported statically by the application shell, which means
deleting the camera folder breaks the build.

The module system (Issue #01) provides everything we need to make the
camera a self-contained, removable module:

- `PluggableModule` protocol + auto-discovery
- Per-module `SettingsStore` with canonical four-endpoint settings surface
- Lazy `import.meta.glob` discovery on the frontend
- Module-contributed sidebar entries

This issue tracks the migration of the camera through that infrastructure.

---

## 2. Goals

1. Move all camera logic into `backend/modules/camera/` and
   `frontend/src/modules/camera/`.
2. Introduce a `CameraSettings` Pydantic schema with the four fields
   that are currently hard-coded (`device_index`, `width`, `height`,
   `jpeg_quality`, `target_fps`).
3. Expose camera settings through the canonical settings endpoints.
4. Validate the **nullable-module guarantee** for camera: deleting
   both folders boots the app cleanly with zero errors.
5. Zero regression: the existing dashboard renders the camera panel
   unchanged.

---

## 3. Non-Goals

- Real-camera (non-OpenCV) backends.
- Multi-camera support (out of scope until a use case appears).
- Recording / playback / snapshot capture.
- Form-from-schema settings UI (Phase 5) — this round only adds the
  schema and the canonical endpoints; the SettingsView placeholder is
  sufficient.

---

## 4. Tasks

### 4.1 Backend

- [ ] Create `backend/modules/camera/__init__.py` re-exporting
      `setup()`.
- [ ] Create `backend/modules/camera/module.py`:

      ```python
      from backend.core.protocols import (
          ModuleManifest, ModuleContext, PluggableModule,
      )
      from .router import router as _router
      from .settings import CameraSettings

      class CameraModule:
          manifest = ModuleManifest(
              id="camera",
              title="Camera",
              version="0.1.0",
              description="Live USB webcam MJPEG stream.",
              settings_panel=True,
          )
          def __init__(self):
              self._router = _router  # share instance with settings?

          def on_load(self, ctx: ModuleContext) -> None:
              # no-op for now; the background frame thread is started
              # lazily on first stream request inside router.py.
              ...

          def on_unload(self) -> None:
              # stop the background frame thread + close cv2.VideoCapture
              ...

          def get_router(self) -> APIRouter:
              return _router

      def setup() -> PluggableModule:
          return CameraModule()
      ```
- [ ] Create `backend/modules/camera/router.py` — move the contents of
      `backend/routers/camera.py` verbatim, but:
  - Convert module-level globals (`_latest_frame`, `_camera_thread`,
    `_camera_lock`) into instance attributes on a `CameraWorker` class
    so the module can start/stop it cleanly in `on_load` / `on_unload`.
  - Add a `GET /api/v1/modules/camera/status` endpoint that returns
    `{ "running": bool, "last_frame_at": iso8601 | null }` so the
    frontend can show a status badge in the settings panel.
- [ ] Create `backend/modules/camera/settings.py`:

      ```python
      from pydantic import BaseModel, Field

      class CameraSettings(BaseModel):
          device_index: int = Field(default=0, ge=0)
          width: int = Field(default=640, ge=160, le=3840)
          height: int = Field(default=480, ge=120, le=2160)
          jpeg_quality: int = Field(default=70, ge=10, le=100)
          target_fps: int = Field(default=15, ge=1, le=60)
      ```

- [ ] Update `backend/modules/camera/module.py` to read settings via
      `ctx.settings.read_all()` inside the worker constructor, and
      re-read them when the next frame is requested (cheap; settings
      are cached in memory by `SettingsStore`).
- [ ] **Settings store wiring:** the registry constructs a
      `SettingsStore(module_id="camera", data_root=..., defaults=CameraSettings())`
      and mounts the canonical four-endpoint router. No additional code
      needed — just ensure the module's `CameraSettings` is passed to
      `SettingsStore` as the `defaults` argument. This requires extending
      `ModuleContext` (or adding a helper) so the module can register
      its defaults before `on_load` runs. **Sub-task:** confirm with
      `core/module_registry.py` whether the registry already supports
      `defaults=` (currently it constructs `SettingsStore(defaults=None)`);
      if not, add a small protocol extension.
- [ ] Update `backend/main.py`:
  - Remove `from routers import camera`.
  - Remove `app.include_router(camera.router)`.
  - The registry's `boot()` picks up `modules/camera/` automatically.
- [ ] Tests in `backend/tests/`:
  - `test_camera_module.py` — `ModuleRegistry.boot([CameraModule()])`
    yields a router at `/api/v1/modules/camera/stream`.
  - `test_camera_settings.py` — `PUT /api/v1/modules/camera/settings`
    with a valid payload persists to
    `data/modules/camera/settings.json` and updates the in-memory
    worker config on the next frame.
  - `test_camera_null.py` — `boot()` with an empty `modules/` package
    logs `mounted=[] skipped=0 missing=0` (this validates the
    nullable-module guarantee).

### 4.2 Frontend

- [ ] Create `frontend/src/modules/camera/index.js`:

      ```js
      import manifest from "./manifest.js";
      import CameraPanel from "./components/CameraPanel.vue";

      const module = {
        manifest,
        sidebar: manifest.sidebar,
        onLoad(/* ctx */) { /* no-op */ },
        onUnload() { /* no-op */ },
      };

      export default module;
      export { CameraPanel };
      ```

- [ ] Create `frontend/src/modules/camera/manifest.js`:

      ```js
      export default {
        id: "camera",
        title: "Camera",
        version: "0.1.0",
        description: "Live USB webcam MJPEG stream.",
        sidebar: {
          id: "camera",
          label: "Camera",
          icon: "...", // SVG string, same shape as builtin entries
          order: 50,
        },
        settingsPanel: true,
      };
      ```

- [ ] Move `frontend/src/components/CameraPanel.vue` to
      `frontend/src/modules/camera/components/CameraPanel.vue`. No
      behavioral change. Replace the hard-coded `/api/v1/camera/stream`
      URL with `/api/v1/modules/camera/stream`.
- [ ] Update `frontend/src/views/DashboardView.vue` to load the camera
      panel lazily:

      ```js
      import { defineAsyncComponent } from 'vue';
      const CameraPanel = defineAsyncComponent(
        () => import('../modules/camera/components/CameraPanel.vue')
      );
      ```

      …and render a placeholder card when the module is absent:

      ```vue
      <div v-if="cameraMounted" class="lg:col-span-2 ...">
        <CameraPanel />
      </div>
      ```

- [ ] Update `frontend/src/stores/registry` consumer(s) — confirm
      `AppSidebar` already merges module-contributed sidebar entries
      (it does per Issue #01's verification). No change.
- [ ] Add `frontend/src/modules/camera/store.js` only if needed for
      runtime state (it is **not** needed for v1; the panel is
      stateless). Skip unless required.
- [ ] Tests:
  - `tests/registry.spec.js` — registry boots with an empty
    `src/modules/` folder without errors.
  - `tests/camera-null.spec.js` — removing `src/modules/camera/`
    leaves the dashboard rendering without a camera slot and the
    build still passes.

### 4.3 Docs

- [ ] Update [`MODULE_SYSTEM_ROADMAP.md`](MODULE_SYSTEM_ROADMAP.md) § 9
      status table — mark Phase 2d ✅ Done.
- [ ] Append a short migration log to
      [`MODULE_SYSTEM_EVALUATION.md`](MODULE_SYSTEM_EVALUATION.md) § 2
      describing any deviation from the audit's plan.
- [ ] Confirm `backend/modules/camera/README.md` exists with a short
      description of what the module does and how to test it.

---

## 5. Acceptance Criteria

A CI run on a clean checkout must demonstrate **all five**:

1. `start_dev.sh` boots both backend and frontend. Backend log
   contains `registry: mounted=['camera'] skipped=0 missing=0`. The
   dashboard renders the camera panel as before.
2. `curl http://localhost:8000/api/v1/modules/camera/settings`
   returns the default payload
   `{ device_index: 0, width: 640, height: 480, jpeg_quality: 70, target_fps: 15 }`.
3. `curl -X PUT -d '{"jpeg_quality":90}' …` updates the file at
   `data/modules/camera/settings.json` atomically (no `.tmp` left
   behind). The next MJPEG frame encodes at quality 90.
4. Remove `backend/modules/camera/` and `frontend/src/modules/camera/`,
   re-run `start_dev.sh`, and visit `/settings`. The app boots with
   `mounted=[]`; the dashboard no longer renders a camera slot; no
   error logs.
5. `npm run build` succeeds with both folders deleted and produces no
   warnings (validates Gotcha #1 — code splitting).

---

## 6. Risks

- **OpenCV file descriptor leak on hot-reload.** If a developer uses
  `uvicorn --reload`, `on_unload()` may be called multiple times. The
  worker class must be idempotent (`cap.release()` is safe to call on
  an already-released capture; just guard the thread stop event).
- **`StreamingResponse` outlives `on_unload()`.** A client mid-stream
  when the module unloads will get a half-closed stream. Acceptable for
  v1; document it in the module README.
- **Frontend cache-buster `?t=…`.** After the URL changes from
  `/api/v1/camera/stream` to `/api/v1/modules/camera/stream`, the Vite
  proxy rewrite must match. No Vite config change expected; verify in
  `vite.config.js`.

---

## 7. Out of Scope

- Multiple cameras.
- Snapshot / recording.
- Form-from-schema settings UI.
- Real-camera HALs (V4L2 direct, GStreamer pipelines).
- Telemetry refactor (Phase 4).

---

## 8. References

- [`MODULE_SYSTEM_ROADMAP.md`](MODULE_SYSTEM_ROADMAP.md) § 4 (frontend
  contract), § 6 (settings), § 12 (gotchas).
- [`MODULE_SYSTEM_EVALUATION.md`](MODULE_SYSTEM_EVALUATION.md) § 2
  (camera audit), § 5 (cross-cutting pitfalls).
- [`backend/core/protocols.py`](backend/core/protocols.py) — the
  contract every module implements.
- [`backend/core/module_registry.py`](backend/core/module_registry.py) —
  discovery + mount + lifecycle.
- [`frontend/src/core/modules/registry.js`](frontend/src/core/modules/registry.js)
  — the frontend discovery loop.