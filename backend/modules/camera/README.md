# `modules/camera/` — Camera module

Live USB webcam MJPEG stream, migrated from the flat
`backend/routers/camera.py` + `frontend/src/components/CameraPanel.vue`
into the registry-driven module system.

## Layout

```
modules/camera/
├── __init__.py        # re-exports setup() so the registry can find it
├── module.py          # CameraModule(PluggableModule) + get_router() + get_settings_model()
├── router.py          # /stream (MJPEG) + /status endpoints + CameraWorker
├── settings.py        # Pydantic CameraSettings (device_index, width, height, jpeg_quality, target_fps)
└── README.md          # this file
```

## Endpoints

| Method | Path                                    | Description |
|--------|-----------------------------------------|-------------|
| GET    | `/api/v1/modules/camera/stream`         | MJPEG `StreamingResponse` from the USB webcam. |
| GET    | `/api/v1/modules/camera/status`         | `{ running: bool, last_frame_at: iso8601 \| null }`. |
| GET    | `/api/v1/modules/camera/settings`       | Merged settings (defaults filled in). |
| GET    | `/api/v1/modules/camera/settings/{k}`   | Single key, 404 if missing. |
| PUT    | `/api/v1/modules/camera/settings`       | Replace payload; merged result returned. |
| PUT    | `/api/v1/modules/camera/settings/{k}`   | Upsert single key; merged result returned. |

The four settings endpoints are mounted by `ModuleRegistry._mount` —
this module does **not** include them itself.

## Lifecycle

* `on_load(ctx)` attaches the per-module `SettingsStore` to the
  background `CameraWorker`. The OpenCV capture is **not** opened here;
  it is opened lazily on the first `/stream` request to avoid wasting
  a handle on deployments that never serve the camera.
* `on_unload()` stops the worker and releases `cv2.VideoCapture`. The
  worker is idempotent so `on_unload` is safe under `uvicorn --reload`.

## Settings schema

`CameraSettings` (Pydantic `BaseModel`):

| Field          | Type | Default | Bounds     | Description |
|----------------|------|---------|------------|-------------|
| `device_index` | int  | 0       | `>= 0`     | `cv2.VideoCapture` device index. |
| `width`        | int  | 640     | 160–3840   | Capture width in pixels. |
| `height`       | int  | 480     | 120–2160   | Capture height in pixels. |
| `jpeg_quality` | int  | 70      | 10–100     | JPEG encoder quality. |
| `target_fps`   | int  | 15      | 1–60       | Cap on stream framerate. |

The worker re-reads the merged settings payload before each frame, so
a `PUT /settings` with `{"jpeg_quality": 90}` takes effect on the next
captured frame — no module restart required.

## Manual smoke test

```bash
# 1. Defaults
curl -s http://localhost:8000/api/v1/modules/camera/settings | jq
# => {"device_index":0,"width":640,"height":480,"jpeg_quality":70,"target_fps":15}

# 2. Update a single key
curl -s -X PUT -H 'Content-Type: application/json' \
  -d '{"jpeg_quality":90}' \
  http://localhost:8000/api/v1/modules/camera/settings | jq

# 3. Stream (binary, won't print)
curl -N http://localhost:8000/api/v1/modules/camera/stream | head -c 100

# 4. Worker status
curl -s http://localhost:8000/api/v1/modules/camera/status | jq
# => {"running":true,"last_frame_at":"2026-07-15T14:28:00.000000+00:00"}
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
  when the module unloads gets a half-closed connection. Acceptable for
  v1; the next-frame `cv2.VideoCapture.release()` does not block the
  event loop.
* No hardware-presence check on import. If OpenCV is missing or no
  camera is attached, the worker logs and disables itself — `/status`
  reports `running=false` instead of crashing.