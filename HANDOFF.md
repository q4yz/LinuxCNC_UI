### Resolution Summary
Added the Camera module's Vue 3 frontend: a Pinia device/preference store, an MJPEG dashboard viewer with camera switching and orientation controls, and a settings panel for per-camera display preferences plus the backend `ip_camera_url` setting.

### Files Modified
- `frontend/src/modules/camera/cameraStore.js`: Added camera discovery, active-camera cycling, validated per-camera preferences, and guarded `localStorage` persistence.
- `frontend/src/modules/camera/components/CameraViewer.vue`: Added the responsive MJPEG `<img>` viewer, explicit stream teardown behavior, camera-name overlay, flip/mirror transforms, and switch-camera FAB.
- `frontend/src/modules/camera/components/CameraSettings.vue`: Added device preference controls and IP camera URL loading/saving through the canonical module settings client.
- `frontend/src/modules/camera/components/CameraPanel.vue`: Converted the existing panel into a compatibility wrapper around `CameraViewer` for the module-owned sidebar view.
- `frontend/src/modules/camera/index.js`: Registered the lazy camera settings panel and exported the new frontend components.
- `frontend/src/App.vue`: Kept settings-only components out of module sidebar view resolution.
- `frontend/src/views/DashboardView.vue`: Replaced the legacy camera panel slot with the new lazy `CameraViewer` while preserving the nullable-module guard.
- `frontend/tests/test-camera-null.mjs`: Updated camera module integration assertions for `CameraViewer`.

### Architectural Decisions
- The viewer uses a keyed `<img v-if="activeCameraId">`; switching or clearing the active ID destroys the old image request so the backend can immediately release its one-camera hardware lock.
- Only `cameraPreferences` is persisted in `localStorage`. Stored data is normalized on read, and unavailable, malformed, blocked, or full storage degrades safely to in-memory preferences.
- Camera IDs are URL-encoded before being sent to `/stream`, which supports device paths and IP camera URLs containing their own query parameters.
- The IP camera URL is saved with `writeKey("ip_camera_url", value)` so unrelated backend camera settings are not replaced. Devices are refreshed after a save so the configured IP camera appears immediately.
- `CameraPanel.vue` remains as a thin compatibility shell, and the generic module-view resolver excludes settings-only components, so the camera sidebar consistently opens the live viewer.

### Testing Verification
- [x] `python -m compileall -q backend` passed.
- [x] `npm --prefix frontend run build` passed; only pre-existing machineconfig dynamic-import and bundle-size warnings were reported.
- [x] `node frontend/scripts/check-store-ids.mjs frontend/src/modules` passed.
- [x] `node --test frontend/tests/test-camera-null.mjs frontend/tests/test-registry.mjs` passed: 9 tests.
- [ ] `python3 -m venv .venv` could not recreate the existing environment because the runner lacks Debian's `ensurepip`/`python3-venv`; the existing functional `.venv` was used and all backend requirements were already satisfied.
- [ ] Root `npm ci` is not applicable because the repository root has no `package-lock.json`. `npm --prefix frontend ci` also reports the pre-existing frontend lockfile is missing `@emnapi/runtime@1.11.3`; the checked-out dependencies were sufficient for the successful production build.
