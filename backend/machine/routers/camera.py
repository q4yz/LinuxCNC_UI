"""Camera module — HTTP router + streaming proxy orchestration.

The previous implementation kept a background thread with an OpenCV
``VideoCapture`` open on every active camera. The fragility of that
loop (Windows C++ exceptions on locked hardware, ``opencv-python``
wheels emitting SIGILL on mismatched ABIs, ``cv2.imencode`` paying a
numpy round-trip per frame) and the cost of supporting per-frame
``jpeg_quality`` / ``target_fps`` knobs pushed the streaming concern
out of the backend.

The camera module is now a thin layer on top of ``ustreamer`` — a
pure-C MJPEG/HTTP server that already powers every 3D-printer camera
panel on the planet (OctoPrint, Mainsail, Fluidd). Each detected
``/dev/videoN`` device gets its own ``ustreamer`` subprocess bound to
``http://127.0.0.1:{8080+index}/?action=stream``; the backend
``/stream`` endpoint proxies those bytes same-origin. The subprocess
supervisor (``UstreamerSupervisor``) lives in
``services/camera/ustreamer_supervisor.py`` — this file owns HTTP
endpoints and the MJPEG proxy orchestration, that one owns process
lifecycle. Camera doesn't fit the Router → Service → DTO → Mapper →
Storage split used elsewhere (no domain data to map, just a process
to supervise and bytes to proxy); this plain module-boundary split is
what actually keeps each file readable as one job instead of two
stapled together.

Endpoints (mounted by the registry under ``/api/v1/modules/camera``):

* ``GET /devices`` — combination of detected USB devices (via
  ``/dev/video*`` + ``v4l2-ctl --list-devices``) plus the IP-camera
  URL configured in settings, so the Vue picker has one place to look.
* ``GET /stream`` — proxied MJPEG bytes (same-origin
  ``StreamingResponse``) for both per-device ``ustreamer`` URLs and
  HTTP / HTTPS IP-camera URLs, or a 503 with a plain-English
  ``message`` describing why the stream cannot be served (dependency
  missing, device absent, platform unsupported, upstream
  unreachable, etc.).
* ``GET /status`` — ``{running, active_id, ustreamer_url, message}``
  for the Settings panel's status row. ``message`` is empty when the
  stream is healthy and carries a single-line operator hint otherwise.
* ``GET /usb`` — kept URL-compatible with the legacy router so the
  frontend picker does not change; today it is the same shape as
  ``GET /devices`` minus the IP-camera row.

Every stream is proxied — the browser never leaves the SPA's origin.
That keeps ``<img src>`` working in dev (Vite proxies ``/api`` to
8000) and in production behind the HTTPS reverse proxy without ever
triggering mixed-content blocking, and keeps upstream credentials
(query parameters or embedded userinfo) out of the browser entirely.

Why no OpenCV / no Python capture? See
``.agent/context/LESSONS_LEARNED.md`` § 4.1 — the original
``opencv-python-headless`` import was the SIGILL trap that crashed
the FastAPI lifespan on misconfigured hosts, and ustreamer is faster,
lighter, and predictable. Do NOT reintroduce ``cv2`` into this
module; the supervisor owns the only process boundary the camera
needs.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from typing import AsyncIterator, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from services.camera.camera_detection import USBDeviceInfo, detect_usb_cameras
from services.camera.camera_mjpeg_proxy import MjpegProxyError, redact_url
from services.camera.shared_mjpeg_proxy import MjpegFanout
from services.camera.ustreamer_supervisor import UstreamerSupervisor

logger = logging.getLogger("backend.camera_service")


# ---------------------------------------------------------------------- #
# Module-level singletons                                                 #
# ---------------------------------------------------------------------- #

# The router is module-level so the registry can mount it; the
# supervisor is module-level so all endpoints share the same
# process table. ``CameraModule.on_load`` wires the settings store
# onto the supervisor via :func:`bind_settings_store`. The class
# itself lives in ``services/camera/ustreamer_supervisor.py``.
router = APIRouter(
    prefix="/api/v1/modules/camera",
    tags=["modules:camera"],
)

_supervisor = UstreamerSupervisor()


# ---------------------------------------------------------------------- #
# Endpoints                                                               #
# ---------------------------------------------------------------------- #


def _safe_host(url: str) -> str:
    """Return a short, display-safe host portion of a URL."""
    try:
        host = urlparse(url).hostname or url
    except Exception:  # noqa: BLE001
        return url[:48]
    return host[:48] if host else url[:48]


@router.get(
    "/usb",
    summary="Detect attached USB cameras",
    description=(
        "Scan ``/dev/video*`` and return one row per device. ``name`` "
        "is the human-readable card string from "
        "``v4l2-ctl --list-devices`` when available; a synthetic "
        "fallback is used otherwise. The endpoint is URL-compatible "
        "with the legacy OpenCV-era router."
    ),
    operation_id="detectUsbCameras",
)
def detect_usb() -> Dict[str, object]:
    devices = detect_usb_cameras()
    return {
        "devices": [
            {"id": d.id, "name": d.name, "index": d.index} for d in devices
        ],
        "platform": sys.platform,
    }


@router.get(
    "/devices",
    summary="List all selectable cameras",
    description=(
        "Combination of the attached USB cameras and any IP-camera "
        "URL configured in the module settings. The ``source`` field "
        "distinguishes ``usb`` rows from ``ip`` rows."
    ),
    operation_id="listCameraDevices",
)
def list_devices() -> Dict[str, object]:
    out: List[Dict[str, str]] = [
        {"id": d.id, "name": d.name, "source": "usb"}
        for d in detect_usb_cameras()
    ]
    # IP camera passthrough: read the optional URL from settings.
    ip_url = _supervisor.read_ip_camera_url()
    if ip_url:
        out.append(
            {
                "id": ip_url,
                "name": f"IP Camera ({_safe_host(ip_url)})",
                "source": "ip",
            }
        )
    return {"devices": out}


@router.get(
    "/stream",
    summary="Get Live MJPEG Stream",
    description=(
        "Returns the MJPEG stream proxied same-origin. For "
        "``/dev/videoN`` sources the per-device ``ustreamer`` URL "
        "(``http://127.0.0.1:{port}/?action=stream``) is proxied; "
        "for HTTP / HTTPS sources the upstream MJPEG bytes are "
        "proxied verbatim (query-parameter credentials pass through "
        "untouched; embedded ``user:pass@host`` userinfo travels in "
        "an ``Authorization`` header so the browser never sees "
        "them). Without query parameters the configured "
        "``default_device_id`` is used; empty on first boot results "
        "in 503. When the stream cannot be served for any reason the "
        "response is a 503 whose ``detail`` is a single-line "
        "operator hint."
    ),
    operation_id="streamCamera",
)
async def camera_stream(
    id: Optional[str] = Query(
        default=None,
        description=(
            "Camera identifier (``/dev/videoN`` path, HTTP/HTTPS URL, "
            "or RTSP URL — RTSP is not supported and returns 503). "
            "Defaults to the configured ``default_device_id``."
        ),
    ),
):
    camera_id = id or _supervisor.read_default_device_id()
    content_type, iterator, sub, fanout_url = await _subscribe_camera(camera_id)

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in iterator:
                yield chunk
        finally:
            MjpegFanout.release(fanout_url, sub)

    return StreamingResponse(
        body(),
        # Pass through the upstream's exact content-type — the
        # ``;boundary=...`` parameter is what lets the browser parse
        # the multipart stream into frames. Without it the browser
        # silently fails to render.
        media_type=content_type,
        headers={
            # Prevent the browser from caching a partial or
            # truncated MJPEG response — the URL already carries
            # ``&t=...`` cache-busters but defense-in-depth is cheap.
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            # Disable nginx buffering in case the operator fronts
            # the backend with a reverse proxy.
            "X-Accel-Buffering": "no",
        },
    )


async def _subscribe_camera(camera_id: str):
    """Resolve any camera id to a fan-out proxy subscription.

    Shared dispatch for ``/stream`` and ``/stream/diagnostic``:
    validates the source (no id / RTSP), proxies IP-camera URLs
    through the fan-out, and spawns-or-reuses the per-device
    ``ustreamer`` for ``/dev/videoN`` sources.

    Returns ``(content_type, iterator, sub, fanout_url)`` — the
    caller owes ``MjpegFanout.release(fanout_url, sub)`` when its
    consumer goes away. Raises ``HTTPException(503)`` with the
    operator-facing reason on any failure; every failure is logged
    at WARNING with a redacted id so the backend log always explains
    a camera 503 (the browser only sees the status code — an
    ``<img>`` element cannot read the response body).
    """
    if not camera_id:
        raise HTTPException(
            status_code=503,
            detail=(
                "No camera selected. Pick a device in the Camera "
                "Settings panel, then request /stream?id=<device_id>."
            ),
        )

    # RTSP cannot be proxied (httpx doesn't speak RTSP and we don't
    # ship ffmpeg / gst-launch). Surface the same 503 shape as every
    # other failure mode so the frontend's diagnostic panel renders
    # it the same way.
    if camera_id.startswith("rtsp://"):
        raise HTTPException(
            status_code=503,
            detail=(
                "RTSP camera URLs are not supported by the IP-camera "
                "proxy. The backend can consume HTTP / HTTPS MJPEG "
                "streams only."
            ),
        )

    # HTTP / HTTPS: proxy the upstream MJPEG through the backend
    # (same path as USB cameras). A 302 redirect would point the
    # browser at the raw upstream URL — mixed content on the HTTPS
    # appliance (and a credential leak: query-param passwords land
    # in the browser's address bar / devtools). The proxy keeps the
    # stream same-origin, forwards query parameters verbatim, and
    # converts embedded ``user:pass@host`` userinfo into an
    # Authorization header the browser never sees.
    if camera_id.startswith(("http://", "https://")):
        content_type, iterator, sub = await _open_stream_subscription(
            camera_id
        )
        return content_type, iterator, sub, camera_id

    # ``/dev/videoN`` (or anything else the supervisor understands).
    # ``spawn_or_reuse`` returns the per-device ustreamer URL
    # (``http://127.0.0.1:{port}/?action=stream``). We proxy that URL
    # through the backend rather than 302-redirecting the browser
    # to it — a redirect would point the browser at the backend host's
    # localhost, which is unreachable from the operator's shop
    # workstation. The proxy makes the camera reachable same-origin.
    try:
        info = _supervisor.spawn_or_reuse(camera_id)
    except RuntimeError as exc:
        logger.warning(
            "camera stream unavailable for %s: %s", camera_id, exc
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    content_type, iterator, sub = await _open_stream_subscription(
        info["url"]
    )
    return content_type, iterator, sub, info["url"]


async def _open_stream_subscription(url: str):
    """Open (or join) the fan-out proxy subscription for ``url``.

    ``MjpegFanout`` keeps a single upstream httpx connection per
    ``url`` and fans the bytes out to every consumer. With N tabs
    viewing the same camera we hit the IP-camera connection cap
    exactly **once**, not N times. The per-subscriber queue's
    drop-oldest overflow policy means a frozen background tab cannot
    freeze everyone else.

    Returns ``(content_type, iterator, sub)``; raises
    ``HTTPException(503)`` — logged — on any upstream failure.
    """
    try:
        proxy = await MjpegFanout.get_or_create(url)
        content_type, iterator = proxy.subscribe()
    except MjpegProxyError as exc:
        logger.warning(
            "camera stream unavailable for %s: %s", redact_url(url), exc
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.ConnectError as exc:
        detail = (
            "Could not connect to the upstream camera. Check the "
            "host, port, and that the camera is reachable from "
            "this backend."
        )
        logger.warning(
            "camera stream unavailable for %s: %s (%s)",
            redact_url(url), detail, exc,
        )
        raise HTTPException(status_code=503, detail=detail) from exc
    except httpx.TimeoutException as exc:
        detail = (
            "Upstream camera timed out. The device is on the "
            "network but stopped responding."
        )
        logger.warning(
            "camera stream unavailable for %s: %s (%s)",
            redact_url(url), detail, exc,
        )
        raise HTTPException(status_code=503, detail=detail) from exc
    except httpx.HTTPError as exc:
        detail = f"Upstream camera connection failed: {exc}"
        logger.warning(
            "camera stream unavailable for %s: %s",
            redact_url(url), detail,
        )
        raise HTTPException(status_code=503, detail=detail) from exc
    return content_type, iterator, iterator._queue


@router.get(
    "/stream/diagnostic",
    summary="Probe a camera stream and report why it cannot be served",
    description=(
        "Runs the exact same upstream attempt as /stream but returns "
        "a JSON verdict (``{ok, message}``) instead of MJPEG bytes. "
        "The frontend calls this when the stream ``<img>`` errors so "
        "the operator sees WHY the camera is down (unreachable / "
        "credentials rejected / login page / dependency missing) "
        "instead of a silent broken image. A successful probe "
        "releases its subscription immediately."
    ),
    operation_id="diagnoseCameraStream",
)
async def camera_stream_diagnostic(
    id: Optional[str] = Query(
        default=None,
        description=(
            "Camera identifier — same vocabulary as /stream. "
            "Defaults to the configured ``default_device_id``."
        ),
    ),
):
    camera_id = id or _supervisor.read_default_device_id()
    if not camera_id:
        return {
            "ok": False,
            "message": (
                "No camera selected. Pick a device in the Camera "
                "Settings panel."
            ),
        }
    try:
        _content_type, _iterator, sub, fanout_url = await _subscribe_camera(
            camera_id
        )
    except HTTPException as exc:
        return {"ok": False, "message": str(exc.detail)}
    except Exception as exc:  # noqa: BLE001 - a diagnostic must never 500
        logger.warning(
            "camera stream diagnostic failed for %s: %s",
            redact_url(camera_id) if "://" in camera_id else camera_id,
            exc,
        )
        return {"ok": False, "message": f"{type(exc).__name__}: {exc}"}
    # Success — release the probe subscription immediately so the
    # fan-out refcount stays consistent with the real ``<img>``
    # streams (the idle TTL tears the upstream down if nobody is
    # watching).
    MjpegFanout.release(fanout_url, sub)
    return {"ok": True, "message": ""}


@router.get(
    "/status",
    summary="Get Supervisor Status",
    description=(
        "Returns ``{running, active_id, ustreamer_url, message}``. "
        "``running`` is true when the supervisor has a live "
        "``ustreamer`` child for the configured default device. "
        "``message`` is a single-line operator hint (empty when the "
        "stream is healthy) that distinguishes 'dependency missing' "
        "from 'device unplugged' from 'platform unsupported'."
    ),
    operation_id="getCameraStatus",
)
def camera_status() -> Dict[str, object]:
    return _supervisor.status()


# ---------------------------------------------------------------------- #
# Module lifecycle hooks                                                  #
# ---------------------------------------------------------------------- #


def bind_settings_store(settings_store) -> None:
    """Attach a SettingsStore to the module-level supervisor.

    Called from :meth:`CameraModule.on_load` once the registry has
    built the per-module :class:`SettingsStore`. Idempotent: calling
    twice with the same store is a no-op.
    """
    _supervisor.bind_settings(settings_store)


def stop_manager() -> None:
    """Tear the supervisor down for ``on_unload``.

    Terminates every spawned ustreamer child and closes every
    still-live MJPEG fan-out proxy. Idempotent.
    """
    _supervisor.shutdown()
    # ``aclose_all`` schedules the per-proxy teardown via
    # ``create_task``; it returns synchronously. The event loop
    # processes the close before uvicorn tears the process down.
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(MjpegFanout.aclose_all())
        else:
            loop.run_until_complete(MjpegFanout.aclose_all())
    except RuntimeError:
        # No event loop bound (very-early-stop path); the proxies
        # are best-effort cleaned up on process exit anyway.
        pass


__all__ = [
    "UstreamerSupervisor",
    "USBDeviceInfo",
    "bind_settings_store",
    "router",
    "stop_manager",
]
