# `modules/camera/` — Camera module

Live USB webcam MJPEG stream, migrated from the flat
`backend/routers/camera.py` + `frontend/src/components/CameraPanel.vue`
into the registry-driven module system. Issue #56 then introduced an
**on-demand** capture lifecycle so a deployment never holds a USB
camera open between requests.

## Layout

```
modules/camera/
├── __init__.py        # re-exports setup() so the registry can find it
├── module.py          # CameraModule(PluggableModule) + get_router() + get_settings_model()
├── router.py          # /usb /devices /stream /status endpoints + StreamManager
├── detection.py       # Linux-first USB camera detection utility
├── settings.py        # Pydantic CameraSettings (resolution, fps, default_device_id, ip_camera_url)
└── README.md          # this file
```

## Endpoints

| Method | Path                                            | Description |
|--------|-------------------------------------------------|-------------|
| GET    | `/api/v1/modules/camera/usb`                    | Detected USB cameras with human-readable names. |
| GET    | `/api/v1/modules/camera/devices`                | USB cameras + configured IP camera URL. |
| GET    | `/api/v1/modules/camera/stream`                 | MJPEG `StreamingResponse` from the default camera. |
| GET    | `/api/v1/modules/camera/stream?id=<camera_id>`  | On-demand MJPEG stream for the given camera. |
| GET    | `/api/v1/modules/camera/status`                 | `{ running, active_id, refcount, last_frame_at }`. |
| GET    | `/api/v1/modules/camera/settings`               | Merged settings (defaults filled in). |
| GET    | `/api/v1/modules/camera/settings/{k}`           | Single key, 404 if missing. |
| PUT    | `/api/v1/modules/camera/settings`               | Replace payload; merged result returned. |
| PUT    | `/api/v1/modules/camera/settings/{k}`           | Upsert single key; merged result returned. |

The four settings endpoints are mounted by `ModuleRegistry._mount` —
this module does **not** include them itself.

## Lifecycle (Issue #56 on-demand contract)

* `on_load(ctx)` attaches the per-module `SettingsStore` to the
  `StreamManager`. No capture is opened at boot; a deployment that
  never serves the camera does not waste an OpenCV handle.
* `on_unload()` calls `stop_manager()` which releases any active
  capture. Idempotent under `uvicorn --reload`.
* `StreamManager.acquire(id)` is called from the `/stream` endpoint on
  the first request. If a different camera is already open it is
  `release()`d *first*, so a "switch camera" call honours the
  on-demand contract immediately.
* `StreamManager.release(id)` is called in a `finally` block from the
  streaming generator, so a client disconnect, server shutdown, or
  unexpected exception all free the hardware at once.
* The streaming generator polls `request.is_disconnected()` between
  frames so a client that drops its TCP connection does not leak a
  capture for the keepalive window.

## Settings schema

`CameraSettings` (Pydantic `BaseModel`):

| Field                | Type | Default | Bounds     | Description |
|----------------------|------|---------|------------|-------------|
| `width`              | int  | 640     | 160–3840   | Capture width in pixels. |
| `height`             | int  | 480     | 120–2160   | Capture height in pixels. |
| `jpeg_quality`       | int  | 70      | 10–100     | JPEG encoder quality. |
| `target_fps`         | int  | 15      | 1–60       | Cap on stream framerate. |
| `default_device_id`  | str  | ""      | —          | Camera used when `/stream` is called without `?id=`. |
| `ip_camera_url`      | str  | ""      | —          | Optional IP-camera URL surfaced through `/devices`. |

The manager re-reads the merged settings payload on every frame, so a
`PUT /settings` with `{"jpeg_quality": 90}` takes effect on the next
captured frame — no module restart required.

## USB camera detection (`detection.py`)

`detect_usb_cameras()` returns a list of `USBDeviceInfo`:

* `id`   — stable identifier (``/dev/videoN`` path on Linux, integer
  index on Windows)
* `name` — human-readable card string (``v4l2-ctl --list-devices``
  card name on Linux; synthetic ``"USB Camera N"`` elsewhere)
* `index` — OpenCV integer index, doubles as a fallback id on Windows

Behaviour by platform:

* **Linux (production target):**
  1. Enumerate `/dev/video*` via `glob`.
  2. Run `v4l2-ctl --list-devices` (2 s timeout) and parse the card
     names. The v4l-utils package is the standard way to query V4L2
     metadata without opening the device.
  3. For any device the parse did not resolve, fall back to an
     OpenCV probe (`cv2.VideoCapture`) and a synthetic name.
  4. OpenCV-probed devices that fail to open are dropped.
* **Windows (developer convenience only):** probe OpenCV indices
  `0..3`; devices that open succeed appear in the list.
* **Other:** returns an empty list.

The function never raises. `v4l2-ctl` missing, `cv2` missing, no
cameras attached — all degrade to an empty list with a `logger.warning`
entry. The endpoint serves the result verbatim.

## IP camera pass-through

Set `ip_camera_url` to any HTTP / RTSP URL OpenCV can decode (e.g.
`http://10.0.0.5/video` or `rtsp://10.0.0.5/stream`). The URL appears
in `GET /devices` with `source == "ip"`, and `GET /stream?id=<url>`
opens it via the same `StreamManager` lifecycle. The capture is
released the moment the client disconnects.

## Manual smoke test

```bash
# 1. Defaults (legacy fields preserved + new ones added)
curl -s http://localhost:8000/api/v1/modules/camera/settings | jq
# => {"width":640,"height":480,"jpeg_quality":70,"target_fps":15,
#     "default_device_id":"","ip_camera_url":""}

# 2. Pick a default camera
curl -s -X PUT -H 'Content-Type: application/json' \
  -d '{"default_device_id":"/dev/video0"}' \
  http://localhost:8000/api/v1/modules/camera/settings | jq

# 3. Enumerate attached USB cameras
curl -s http://localhost:8000/api/v1/modules/camera/usb | jq

# 4. Stream a specific camera (binary, won't print)
curl -N 'http://localhost:8000/api/v1/modules/camera/stream?id=/dev/video0' | head -c 100

# 5. Worker status — refcount > 0 while streaming, 0 once the client drops
curl -s http://localhost:8000/api/v1/modules/camera/status | jq
# => {"running":true,"active_id":"/dev/video0","refcount":1,"last_frame_at":"..."}
```

## Nullable-module guarantee

Removing both `backend/modules/camera/` **and**
`frontend/src/modules/camera/` is the documented happy path:

* Backend boots with `registry: mounted=[] skipped=0 missing=0`.
* The dashboard's `DashboardView.vue` skips the camera slot because
  `registry.modules.has('camera')` returns `false`.
* `npm run build` still succeeds because the Vite glob is lazy
  (`import.meta.glob('../modules/*/index.js', { eager: false })`).

See `MODULE_SYSTEM_ROADMAP.md` § 12 Gotcha #1 for the design rationale.

## Known caveats

* `StreamingResponse` may outlive `on_unload()`: a client mid-stream
  when the module unloads gets a half-closed connection. The next
  `cv2.VideoCapture.release()` from the `finally` block still frees
  the hardware lock; the client just sees a half-streamed frame.
* `v4l2-ctl` is not installed on every container image. The detection
  utility tolerates this and falls back to OpenCV probing — the
  human-readable name may be the synthetic fallback instead.
* On Windows the OpenCV index probe opens and immediately closes
  each candidate device (indices 0..3). On a machine with no cameras
  the probe takes <1 s total and reports an empty list.
* The OpenCV import is deferred to the first `acquire()` call so
  unit tests and CI environments without a working OpenCV install
  can still import this module without raising. If the import
  fails, `/stream` returns 503 and `/usb` returns an empty list.