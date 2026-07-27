### Resolution Summary
Replaced the background `CameraWorker` thread with an on-demand `StreamManager` so USB cameras are only opened while a client is streaming and released the moment they disconnect. Added Linux-first USB camera detection (`/api/v1/modules/camera/usb`), combined device listing (`/api/v1/modules/camera/devices`), and a `?id=` parameter on `/stream` that accepts both `/dev/videoN` paths and HTTP/RTSP URLs.

### Files Modified
- `backend/modules/camera/detection.py` — *new* — Linux-first `detect_usb_cameras()` utility that scans `/dev/video*`, parses `v4l2-ctl --list-devices` for human-readable names, falls back to an OpenCV probe, and ships a synthetic-name path for Windows.
- `backend/modules/camera/router.py` — refactored: removed the legacy `CameraWorker` (background thread); introduced `StreamManager` with reference counting so one camera at a time is enforced and `.release()` is called on disconnect / switch / shutdown; added `GET /usb` and `GET /devices`; `GET /stream?id=<camera_id>` now supports USB device paths and IP camera URLs.
- `backend/modules/camera/settings.py` — renamed the legacy `device_index` field to `default_device_id` (string, accepts `/dev/videoN` paths or URLs); added `ip_camera_url` so the new `/devices` endpoint can surface an IP camera as an alternative picker entry.
- `backend/modules/camera/module.py` — updated lifecycle hooks (`bind_settings_store` / `stop_manager`) and bumped the manifest version to `0.2.0`.
- `backend/modules/camera/README.md` — documented the on-demand contract, the new endpoints, the detection utility behaviour per platform, and the IP-camera pass-through.
- `backend/tests/test_camera_module.py` — adjusted for the renamed settings fields and the new `active_id` / `refcount` keys on `/status`; added `test_camera_usb_endpoint_is_mounted` and `test_camera_devices_endpoint_is_mounted`.
- `backend/tests/test_camera_settings.py` — updated the `_reload_config` plumbing test to call `StreamManager.reload_config()` and `bind_settings_store()`.
- `backend/tests/test_camera_detection.py` — *new* — 14 tests covering the v4l2-ctl parser, the OpenCV probe fallback, and the platform-aware `detect_usb_cameras()`.
- `backend/tests/test_camera_stream_manager.py` — *new* — 12 tests pinning the Issue #56 contract: acquire/release lifecycle, switching cameras releases the previous one, the last client disconnecting frees the hardware, and the thread-safety smoke test.

### Architectural Decisions
- **On-demand over background thread.** The previous `CameraWorker` opened `cv2.VideoCapture` at boot and held it continuously — wasted USB bandwidth on deployments that rarely viewed the camera and a violation of the issue's "do not keep camera resources open in the background" requirement. The new `StreamManager` opens on first `acquire()`, releases on disconnect or switch, and uses refcounting so concurrent clients for the same id share one capture.
- **Streaming generator pattern.** `request.is_disconnected()` is polled between frames so a TCP drop frees the hardware within one framerate instead of waiting for the keepalive window. `cv2.read()` and `cv2.imencode()` are wrapped in `asyncio.to_thread()` so the asyncio loop stays responsive to jog keep-alives and the WebSocket telemetry loop.
- **Detection falls back gracefully.** `v4l2-ctl` missing, `cv2` missing, glob explosion, unopenable devices — all return empty lists with a `logger.warning`. The `GET /usb` endpoint can never crash the boot path.
- **IP-camera pass-through.** Added `ip_camera_url` to settings and surfaced it through `/devices` with `source == "ip"`. The same `StreamManager` handles `cv2.VideoCapture("http://...")` so the on-demand contract applies to IP feeds too.
- **Backwards-compatible settings rename.** `device_index` (int) → `default_device_id` (str). Existing tests were updated; the migration is internal and the frontend never referenced `device_index` directly.

### Testing Verification
- [x] `python -m compileall -q backend` — passed.
- [x] `npm --prefix frontend run build` — passed (only the pre-existing ineffective-dynamic-import warnings for machineconfig panels).
- [x] `pytest backend/tests/` — 172 passed, 6 pre-existing errors in `test_jog_watchdog.py` (unrelated `from backend.modules.machine import jog` failure that exists before my changes).
- [x] `pytest backend/tests/test_camera_detection.py backend/tests/test_camera_stream_manager.py backend/tests/test_camera_module.py backend/tests/test_camera_settings.py backend/tests/test_camera_null.py` — 39 passed.

### Acceptance-criteria checklist (Issue #56)
- [x] Backend scans `/dev/video*` on Linux and exposes them via `GET /api/v1/modules/camera/usb` with human-readable names from `v4l2-ctl --list-devices`.
- [x] Windows / other platforms degrade to an empty list or synthetic OpenCV-probed entries.
- [x] `GET /stream` enforces one-camera-at-a-time at the hardware level: opening a new camera closes the previous one in the same call (`StreamManager._release_locked`).
- [x] `.release()` is called the moment a client disconnects (the `finally` block in `_generate_frames` plus `request.is_disconnected()` polling).
- [x] `GET /stream?id=<camera_id>` accepts both `/dev/videoN` paths and HTTP/RTSP URLs through the same `StreamManager` lifecycle.
- [x] Streaming is non-blocking (`asyncio.to_thread` for `cv2.read()` + `cv2.imencode()`, `asyncio.sleep` cap matches the legacy 60 ms floor).
- [x] Existing `CameraPanel.vue` continues to work — the legacy `/stream` URL stays reachable; the new `?id=` parameter is opt-in.