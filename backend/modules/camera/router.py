"""Camera module — HTTP router + on-demand stream manager.

This file replaces the previous ``CameraWorker`` (a background thread
that held the OpenCV capture open continuously) with an *on-demand*
streaming model. The contract documented in Issue #56 is:

* The frontend is allowed to view **one** camera at a time.
* The backend must not keep any camera handle open in the background.
* When a stream request arrives, open the capture; when it ends
  (client disconnect or another stream is requested), release the
  capture immediately so the USB bandwidth and hardware lock are
  freed.
* The MJPEG stream must be non-blocking (asyncio generator with
  ``request.is_disconnected()`` polling) so it does not interfere with
  the main LinuxCNC polling loop.

Endpoints (mounted by the registry under ``/api/v1/modules/camera``):

* ``GET /usb``   — list the USB cameras currently attached, with
  human-readable names (Linux: ``v4l2-ctl``; Windows: OpenCV probe).
* ``GET /devices`` — combination of USB + the IP-camera URL configured
  in settings, so the frontend picker has one place to look.
* ``GET /stream`` — legacy default-camera stream (uses the configured
  ``default_device_id``).
* ``GET /stream?id=<camera_id>`` — explicit on-demand stream. The
  ``camera_id`` is either a ``/dev/videoN`` path or an HTTP/RTSP URL.
* ``GET /status`` — small JSON endpoint for the settings panel.

The previous ``/stream`` endpoint stayed URL-compatible because it just
defaults to the configured ``default_device_id`` setting; clients that
already point at ``/stream`` keep working without query parameters.

The module-level :class:`StreamManager` (one instance per process) is
the single source of truth for "which camera is open right now". It
uses a reference count so a slow client that requests the same stream
twice does not race with itself; an *idle* camera (refcount == 0) is
released even if another stream for the same id is queued.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import threading
from datetime import datetime, timezone
from typing import AsyncIterator, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .detection import USBDeviceInfo, detect_usb_cameras
from .settings import CameraSettings
import cv2 as _cv2

logger = logging.getLogger("backend.modules.camera")


# ---------------------------------------------------------------------- #
# Module-level singletons                                                 #
# ---------------------------------------------------------------------- #


# The router is module-level so the registry can mount it; the
# StreamManager is module-level so all endpoints share the same
# capture lifecycle. ``CameraModule.on_load`` wires the settings store
# onto the manager via :func:`bind_settings_store`.
router = APIRouter(tags=["modules:camera"])

# ``StreamManager`` is defined further down — the import order is
# (router, manager) first so the endpoints can reference the manager
# even though the class itself is declared below.
_stream_manager: "StreamManager"


# ---------------------------------------------------------------------- #
# Pydantic response models                                                #
# ---------------------------------------------------------------------- #


class USBDevicePayload(BaseModel):
    """One row in the ``/usb`` response."""

    id: str = Field(..., description="Stable camera identifier (path or index).")
    name: str = Field(..., description="Human-readable camera name.")
    index: int = Field(..., description="OpenCV integer index for this device.")


class USBDevicesResponse(BaseModel):
    """``GET /usb`` response payload."""

    devices: List[USBDevicePayload] = Field(
        default_factory=list,
        description="Detected USB cameras (may be empty).",
    )
    platform: str = Field(
        ...,
        description="OS the detection ran on (linux, win32, other).",
    )


class DevicePayload(BaseModel):
    """One row in the ``/devices`` response (USB + IP cameras)."""

    id: str = Field(..., description="Stable camera identifier.")
    name: str = Field(..., description="Human-readable camera name.")
    source: str = Field(
        ...,
        description="Origin of the entry: ``usb`` or ``ip``.",
    )


class DevicesResponse(BaseModel):
    """``GET /devices`` response payload."""

    devices: List[DevicePayload] = Field(
        default_factory=list,
        description="All selectable cameras (USB + IP cameras).",
    )


class StreamStatusResponse(BaseModel):
    """``GET /status`` response payload."""

    running: bool = Field(
        ...,
        description="Whether a stream is currently being served.",
    )
    active_id: Optional[str] = Field(
        default=None,
        description="Identifier of the camera currently open.",
    )
    refcount: int = Field(
        default=0,
        description="Number of active stream handles.",
    )
    last_frame_at: Optional[str] = Field(
        default=None,
        description=(
            "ISO-8601 timestamp of the most recently yielded frame, "
            "or ``null`` if no frame has been yielded."
        ),
    )


# ---------------------------------------------------------------------- #
# StreamManager                                                           #
# ---------------------------------------------------------------------- #


class StreamManager:
    """One-camera-at-a-time manager for the MJPEG endpoint.

    A single capture is held under :attr:`_active_cap` and shared
    between all streaming clients. Reference counting lets a slow
    client safely issue two requests for the same id without racing
    itself; the capture is released only when *every* client has
    dropped or switched cameras.

    Thread-safety
    -------------
    Public methods (``acquire``, ``release``, ``shutdown``,
    ``status``, ``mark_frame``) take :attr:`_lock` so concurrent
    FastAPI threadpool tasks (the stream endpoint runs in a worker
    thread via the asyncio generator bridge) cannot tear the capture
    down twice.

    Why not just a module-level capture?
    ------------------------------------
    Holding the capture open between requests would violate the
    on-demand contract from Issue #56: ``/dev/video*`` bandwidth must
    be released the moment no client is watching.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_id: Optional[str] = None
        self._active_cap = None  # cv2.VideoCapture (typed as Any)
        self._refcount: int = 0
        self._last_frame_at: Optional[datetime] = None
        self._settings_store = None  # late-bound by bind_settings
        self._cv2_disabled = False

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    def bind_settings(self, settings_store) -> None:
        """Attach the module's SettingsStore. Idempotent."""
        self._settings_store = settings_store

    def shutdown(self) -> None:
        """Release the active capture and reset the refcount."""
        with self._lock:
            self._release_locked()

    # ------------------------------------------------------------------ #
    # Accessors                                                          #
    # ------------------------------------------------------------------ #

    def status(self) -> dict:
        """Return a small JSON-serialisable snapshot for ``GET /status``."""
        with self._lock:
            running = self._active_cap is not None and self._refcount > 0
            last = self._last_frame_at
            return {
                "running": running,
                "active_id": self._active_id,
                "refcount": self._refcount,
                "last_frame_at": last.isoformat() if last is not None else None,
            }

    def mark_frame(self) -> None:
        """Stamp ``_last_frame_at`` after a successful frame yield."""
        with self._lock:
            self._last_frame_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------ #
    # Settings passthrough                                                #
    # ------------------------------------------------------------------ #

    def reload_config(self) -> CameraSettings:
        """Build a :class:`CameraSettings` from the store.

        Thread-safe: re-reads happen on every frame, but the underlying
        store caches its payload so the cost is one dict copy. Falls
        back to defaults on validation errors so a transient bad PUT
        never crashes the streaming loop.
        """
        try:
            if self._settings_store is None:
                return CameraSettings()
            payload = self._settings_store.read_all()
            return CameraSettings(**payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "StreamManager: invalid settings payload (%s); using defaults",
                exc,
            )
            return CameraSettings()

    def read_default_device_id(self) -> Optional[str]:
        """Return the configured ``default_device_id`` (or ``None``)."""
        cfg = self.reload_config()
        value = getattr(cfg, "default_device_id", "")
        return value or None

    def read_ip_camera_url(self) -> Optional[str]:
        """Return the configured ``ip_camera_url`` (or ``None``)."""
        cfg = self.reload_config()
        value = getattr(cfg, "ip_camera_url", "")
        return value or None

    # ------------------------------------------------------------------ #
    # Acquire / Release                                                  #
    # ------------------------------------------------------------------ #

    def acquire(self, camera_id: str):
        """Open (or share) the capture for ``camera_id``.

        Returns the OpenCV capture object so the caller can call
        ``.read()`` directly. Raises :class:`RuntimeError` if the
        capture cannot be opened — callers should translate that into
        an actionable HTTP error.
        """
        if not camera_id:
            raise RuntimeError("camera_id is required")

        # Lazy-import cv2 and remember the reference so the rest of
        # ``acquire`` does not have to repeat the import. We catch the
        # import failure *and* attribute-access failures because some
        # environments ship a partially-broken cv2 that imports but
        # cannot resolve ``VideoCapture`` (typically missing
        # libavdevice / GStreamer).
        try:
            import cv2 as _cv2  # type: ignore
            _ = _cv2.VideoCapture  # attribute probe
        except Exception as exc:  # noqa: BLE001
            self._cv2_disabled = True
            raise RuntimeError(
                f"OpenCV is not available on the server: {exc}"
            ) from exc

        with self._lock:
            # Fast path: already serving this id.
            if (
                self._active_id == camera_id
                and self._active_cap is not None
                and self._active_cap.isOpened()
            ):
                self._refcount += 1
                logger.debug(
                    "StreamManager.acquire: reusing %s (refcount=%d)",
                    camera_id,
                    self._refcount,
                )
                return self._active_cap

            # Release any active capture first so a "switch camera"
            # request honours the on-demand contract.
            self._release_locked()

            source = camera_id
            backend_api = _cv2.CAP_ANY
            # If it's a pure number string like "0", cast it to an int for Windows
            if isinstance(source, str) and source.isdigit():
                source = int(source)

                if sys.platform == 'win32':
                    backend_api = _cv2.CAP_DSHOW

            cap = _cv2.VideoCapture(source, backend_api)
            if cap is None or not cap.isOpened():
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:  # noqa: BLE001
                        pass
                raise RuntimeError(
                    f"Cannot open camera source: {camera_id!r}"
                )

            # Apply resolution settings from the module config.
            # Failures are logged but non-fatal — the driver may
            # ignore the request and produce whatever it likes.
            cfg = self.reload_config()
            try:
                cap.set(_cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
                cap.set(_cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "StreamManager: cap.set resolution failed: %s", exc
                )

            self._active_cap = cap
            self._active_id = camera_id
            self._refcount = 1
            logger.info(
                "StreamManager: opened capture id=%s (refcount=1)", camera_id
            )
            return cap

    def release(self, camera_id: str) -> None:
        """Decrement the refcount for ``camera_id`` and release at zero.

        A release against a stale id (i.e. the active id has already
        been switched) is a no-op. This keeps clients that disconnect
        asynchronously from racing with the manager.
        """
        with self._lock:
            if self._active_id != camera_id:
                return
            if self._refcount <= 0:
                return
            self._refcount -= 1
            logger.debug(
                "StreamManager.release: id=%s refcount=%d",
                camera_id,
                self._refcount,
            )
            if self._refcount <= 0:
                self._release_locked()

    def _release_locked(self) -> None:
        """Release the active capture. Caller must hold :attr:`_lock`."""
        cap = self._active_cap
        self._active_cap = None
        self._active_id = None
        self._refcount = 0
        if cap is not None:
            try:
                cap.release()
            except Exception as exc:  # noqa: BLE001 - cv2 internals vary
                logger.debug("StreamManager: cap.release() raised %s", exc)
            logger.info("StreamManager: released capture.")


# ---------------------------------------------------------------------- #
# Streaming generator                                                     #
# ---------------------------------------------------------------------- #


async def _generate_frames(
    camera_id: str, request: Request
) -> AsyncIterator[bytes]:
    """Async MJPEG generator for a single client.

    The capture is opened via :meth:`StreamManager.acquire` (which
    releases any other camera first) and closed in a ``finally`` block
    so a client disconnect, server shutdown, or unexpected exception
    all free the hardware immediately.

    The loop polls ``request.is_disconnected()`` between frames so a
    client that drops its TCP connection does not leak a capture for
    the entire ~250 ms keepalive window.
    """
    try:
        cap = await asyncio.to_thread(_stream_manager.acquire, camera_id)
    except RuntimeError as exc:
        # DO NOT raise HTTPException here. The StreamingResponse has already started
        # and sent the 200 OK headers. Exiting cleanly terminates the stream.
        logger.error("Failed to start stream for camera_id=%s: %s", camera_id, exc)
        return

    try:
        while True:
            # Stop the moment the client goes away.
            if await request.is_disconnected():
                logger.info(
                    "Stream: client disconnected (camera_id=%s)", camera_id
                )
                break

            # Reload config from the settings store on every frame so
            # a PUT on /settings takes effect on the next frame.
            cfg = await asyncio.to_thread(_stream_manager.reload_config)

            # ``read()`` is blocking; run it in a worker thread so the
            # asyncio loop stays responsive to the jog keep-alive
            # endpoint and the WebSocket telemetry loop.
            # Wrap the read call to catch exploding Windows drivers
            try:
                ok, frame = cap.read()
            except _cv2.error as e:
                logger.warning(
                    "Stream: C++ exception during cv2.read for camera_id=%s; stopping. (%s)",
                    camera_id, e
                )
                break  # Break the loop to trigger the finally block
            except Exception as e:
                logger.warning("Stream: Unexpected error reading camera_id=%s: %s", camera_id, e)
                break
            if not ok:
                logger.warning(
                    "Stream: cv2.read failed for camera_id=%s; stopping.",
                    camera_id,
                )
                break

            # ``imencode`` itself is fast (<10 ms for 640x480) but we
            # still keep it off the event loop for symmetry with
            # ``read()``.
            ok, buffer = await asyncio.to_thread(
                _imencode_jpeg, frame, cfg.jpeg_quality
            )
            if ok:
                _stream_manager.mark_frame()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + bytes(buffer)
                    + b"\r\n"
                )

            # Sleep cap so the asyncio loop keeps breathing for jog
            # keep-alives. Floor at 60 ms (matches the legacy router).
            sleep_seconds = max(1.0 / cfg.target_fps, 0.06)
            await asyncio.sleep(sleep_seconds)
    finally:
        # Always release — disconnect, exception, server shutdown.
        await asyncio.to_thread(_stream_manager.release, camera_id)


def _imencode_jpeg(frame, quality: int):
    """Helper run in a worker thread so the asyncio loop stays free.

    Returns ``(ok, buffer_or_none)`` so the caller can detect failure.
    """
    try:
        import cv2  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.error("Stream: cv2 import failed inside encode: %s", exc)
        return False, None
    return cv2.imencode(
        ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]
    )


# ---------------------------------------------------------------------- #
# Endpoints                                                               #
# ---------------------------------------------------------------------- #


@router.get(
    "/usb",
    response_model=USBDevicesResponse,
    summary="Detect attached USB cameras",
    description=(
        "Scan ``/dev/video*`` (Linux) or probe OpenCV indices "
        "(Windows) and return one row per device. ``name`` is the "
        "human-readable card string from ``v4l2-ctl --list-devices`` "
        "when available; a synthetic fallback is used otherwise."
    ),
    operation_id="detectUsbCameras",
)
def detect_usb() -> USBDevicesResponse:
    import sys as _sys

    devices = detect_usb_cameras()
    return USBDevicesResponse(
        devices=[
            USBDevicePayload(id=d.id, name=d.name, index=d.index)
            for d in devices
        ],
        platform=_sys.platform,
    )


def _safe_host(url: str) -> str:
    """Return a short, display-safe host portion of a URL."""
    try:
        host = urlparse(url).hostname or url
    except Exception:  # noqa: BLE001
        return url[:48]
    return host[:48] if host else url[:48]


@router.get(
    "/devices",
    response_model=DevicesResponse,
    summary="List all selectable cameras",
    description=(
        "Combination of the attached USB cameras and any IP-camera "
        "URL configured in the module settings. The ``source`` field "
        "distinguishes ``usb`` rows from ``ip`` rows."
    ),
    operation_id="listCameraDevices",
)
def list_devices() -> DevicesResponse:
    out: List[DevicePayload] = [
        DevicePayload(id=d.id, name=d.name, source="usb")
        for d in detect_usb_cameras()
    ]
    # IP camera passthrough: read the optional URL from settings.
    ip_url = _stream_manager.read_ip_camera_url()
    if ip_url:
        out.append(
            DevicePayload(
                id=ip_url,
                name=f"IP Camera ({_safe_host(ip_url)})",
                source="ip",
            )
        )
    return DevicesResponse(devices=out)


@router.get(
    "/stream",
    summary="Get Live MJPEG Stream",
    description=(
        "Streams live MJPEG video from the requested camera. Without "
        "query parameters the configured ``default_device_id`` is used "
        "(empty on first boot, which results in 503 — pick a device "
        "first via ``GET /usb``). With ``?id=…`` the supplied "
        "identifier is opened on-demand; switching cameras releases "
        "the previous capture immediately."
    ),
    operation_id="streamCamera",
)
def camera_stream(
    request: Request,
    id: Optional[str] = Query(
        default=None,
        description=(
            "Camera identifier (``/dev/videoN`` path or HTTP/RTSP URL). "
            "Defaults to the configured ``default_device_id``."
        ),
    ),
) -> StreamingResponse:
    camera_id = id or _stream_manager.read_default_device_id()
    if not camera_id:
        raise HTTPException(
            status_code=503,
            detail=(
                "No camera selected. Call GET /usb to enumerate devices, "
                "then re-request /stream?id=<device_id>."
            ),
        )
    return StreamingResponse(
        _generate_frames(camera_id, request),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get(
    "/status",
    response_model=StreamStatusResponse,
    summary="Get Stream Manager Status",
    description=(
        "Returns ``{running, active_id, refcount, last_frame_at}``. "
        "``running`` is true while at least one client is being "
        "served. ``refcount`` shows how many concurrent clients are "
        "sharing the active capture."
    ),
    operation_id="getCameraStatus",
)
def camera_status() -> StreamStatusResponse:
    snapshot = _stream_manager.status()
    return StreamStatusResponse(**snapshot)


# ---------------------------------------------------------------------- #
# Late binding                                                            #
# ---------------------------------------------------------------------- #

# Instantiate the singleton *after* :class:`StreamManager` is declared so
# the class body is visible at module-load time.
_stream_manager = StreamManager()


def bind_settings_store(settings_store) -> None:
    """Attach a SettingsStore to the module-level StreamManager.

    Called from :meth:`CameraModule.on_load` once the registry has built
    the per-module :class:`SettingsStore`. Idempotent: calling twice
    with the same store is a no-op.
    """
    _stream_manager.bind_settings(settings_store)


def stop_manager() -> None:
    """Tear the manager down for ``on_unload``.

    Releases any active capture. Idempotent.
    """
    _stream_manager.shutdown()


__all__ = [
    "StreamManager",
    "USBDeviceInfo",
    "bind_settings_store",
    "router",
    "stop_manager",
]