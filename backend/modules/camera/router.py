"""Camera module — HTTP router + background frame worker.

This file replaces the flat ``backend/routers/camera.py`` that used to be
imported statically by ``main.py``. Behaviour is intentionally identical
from the client side:

* ``GET /api/v1/modules/camera/stream`` — MJPEG ``StreamingResponse``
  against the most recent frame captured by a single background
  thread. The thread is owned by a :class:`CameraWorker` instance so the
  module can start it in :meth:`CameraModule.on_load` and stop it in
  :meth:`CameraModule.on_unload`.
* ``GET /api/v1/modules/camera/status`` — small JSON endpoint that the
  frontend settings panel can poll to render a "running / offline"
  badge.

Settings (resolution, JPEG quality, target FPS, device index) flow
through the canonical four-endpoint settings surface that the registry
already mounts at ``/api/v1/modules/camera/settings``. The worker
re-reads the merged settings payload before each frame so a
``PUT settings`` updates the next frame without restart — see
:meth:`CameraWorker._reload_config`.

The OpenCV import is deferred to the first ``start()`` call so that
unit tests and CI environments without a working OpenCV install can
still import this module without raising.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from .settings import CameraSettings

logger = logging.getLogger("backend.modules.camera")


# ---------------------------------------------------------------------- #
# Worker                                                                 #
# ---------------------------------------------------------------------- #


class CameraWorker:
    """Background USB webcam frame producer.

    Owns a single daemon thread plus a :class:`threading.Lock` that
    guards reads of the latest frame. The worker is **idempotent**:
    ``start()`` is a no-op when the thread is already alive and
    ``stop()`` is safe to call when nothing is running. This matters
    because the registry may invoke :meth:`CameraModule.on_unload`
    more than once under ``uvicorn --reload``.

    The worker reads its operating parameters (resolution, JPEG
    quality, target FPS, device index) from the module's
    :class:`core.settings_store.SettingsStore` before every frame so a
    PUT on the settings endpoint takes effect on the next frame
    without needing a module restart. Settings are cached in memory by
    the store, so the reload is cheap.

    The OpenCV import is deferred to :meth:`start` so unit tests can
    instantiate the worker without ``cv2`` being installed; if
    OpenCV is missing the worker logs and disables itself instead of
    crashing the boot.
    """

    def __init__(
        self,
        settings_store,  # core.settings_store.SettingsStore
    ) -> None:
        self._settings = settings_store
        self._latest_frame: Optional[bytes] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cap = None  # cv2.VideoCapture — typed as Any to avoid a hard import
        self._last_frame_at: Optional[datetime] = None
        self._cv2_disabled = False

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Spin up the background frame thread (no-op if already running)."""
        if self._thread is not None and self._thread.is_alive():
            return
        if self._cv2_disabled:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="camera-worker",
            daemon=True,
        )
        self._thread.start()
        logger.info("Camera worker started.")

    def stop(self) -> None:
        """Stop the background thread and release the capture.

        Idempotent — safe to call multiple times. After ``stop()``
        the worker will not produce more frames until ``start()`` is
        called again.
        """
        self._stop_event.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=1.0)
        cap = self._cap
        self._cap = None
        if cap is not None:
            try:
                cap.release()
            except Exception as exc:  # noqa: BLE001 - cv2 internals vary
                logger.debug("CameraWorker: cap.release() raised %s", exc)
        with self._lock:
            self._latest_frame = None
        logger.info("Camera worker stopped.")

    # ------------------------------------------------------------------ #
    # Status / accessors                                                 #
    # ------------------------------------------------------------------ #

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_frame_at(self) -> Optional[datetime]:
        return self._last_frame_at

    def get_latest_frame(self) -> Optional[bytes]:
        """Return a copy of the latest JPEG bytes (or ``None``)."""
        with self._lock:
            return self._latest_frame

    # ------------------------------------------------------------------ #
    # Frame loop                                                         #
    # ------------------------------------------------------------------ #

    def _reload_config(self):
        """Read the merged settings payload and build a config dict.

        Re-reads happen on every frame. Settings are cached in memory
        by ``SettingsStore`` so the cost is one dict copy. We swallow
        invalid payloads (they would already have been rejected by the
        PUT endpoint validation, but defensive coding never hurts) and
        fall back to ``CameraSettings()`` defaults.
        """
        try:
            payload = self._settings.read_all()
            cfg = CameraSettings(**payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "CameraWorker: invalid settings payload (%s); using defaults",
                exc,
            )
            cfg = CameraSettings()
        return cfg

    def _run(self) -> None:
        """Body of the background thread.

        Opens the capture inside the thread so ``start()`` itself stays
        fast (no blocking I/O on the asyncio event loop). On OpenCV
        import failure we log once and disable the worker so subsequent
        ``start()`` calls become no-ops.
        """
        try:
            import cv2  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "CameraWorker: cv2 import failed (%s); camera disabled.",
                exc,
            )
            self._cv2_disabled = True
            return

        cfg = self._reload_config()
        cap = cv2.VideoCapture(cfg.device_index)
        if not cap.isOpened():
            logger.error(
                "CameraWorker: failed to open device index %s.", cfg.device_index
            )
            cap.release()
            self._cv2_disabled = True
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
        self._cap = cap

        try:
            while not self._stop_event.is_set():
                cfg = self._reload_config()
                ok, frame = cap.read()
                if not ok:
                    logger.error("CameraWorker: failed to read frame.")
                    time.sleep(1.0)
                    continue

                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), cfg.jpeg_quality]
                ok, buffer = cv2.imencode(".jpg", frame, encode_param)
                if ok:
                    with self._lock:
                        self._latest_frame = buffer.tobytes()
                        self._last_frame_at = datetime.now(timezone.utc)

                # Cap framerate to ``target_fps`` while still yielding
                # the OS so other threads (e.g. FastAPI keep-alives) get
                # scheduled promptly. The 60 ms floor is the historical
                # default — preserved here as a hard lower bound.
                sleep_seconds = max(1.0 / cfg.target_fps, 0.06)
                time.sleep(sleep_seconds)
        finally:
            try:
                cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None


# ---------------------------------------------------------------------- #
# Module-level singleton                                                  #
# ---------------------------------------------------------------------- #

# The router is module-level so the registry can mount it; the worker
# is also module-level so the ``/stream`` and ``/status`` endpoints
# share the same capture. ``CameraModule.on_load`` wires the settings
# store onto the worker via :func:`bind_worker_settings`.
router = APIRouter(tags=["modules:camera"])
_worker = CameraWorker(settings_store=None)
_settings_store_ref = {"store": None}  # late-bound by CameraModule.on_load


def bind_worker_settings(settings_store) -> None:
    """Attach a SettingsStore to the module-level worker.

    Called from :meth:`CameraModule.on_load` once the registry has built
    the per-module :class:`SettingsStore`. Idempotent.
    """
    if _settings_store_ref["store"] is settings_store:
        return
    _settings_store_ref["store"] = settings_store
    _worker._settings = settings_store


def start_worker() -> None:
    """Start the module-level worker (used by the streaming endpoint)."""
    _worker.start()


def stop_worker() -> None:
    """Stop the module-level worker (called by ``on_unload``)."""
    _worker.stop()


# ---------------------------------------------------------------------- #
# Endpoints                                                              #
# ---------------------------------------------------------------------- #


async def _generate_frames():
    """Async MJPEG generator.

    Lazily starts the worker so a connection that opens but immediately
    drops does not waste an OpenCV handle. The asyncio sleep is the
    framerate cap; it is intentionally identical to the historical
    ``routers/camera.py`` value so behaviour does not regress.
    """
    start_worker()
    while True:
        frame = _worker.get_latest_frame()
        if frame is not None:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            )
        # Hard floor of 60 ms to keep the asyncio loop breathing for
        # jog keep-alives; matches the legacy router.
        await asyncio.sleep(0.06)


@router.get(
    "/stream",
    summary="Get Live Camera Stream",
    description="Streams live MJPEG video from the primary USB webcam.",
)
def camera_stream() -> StreamingResponse:
    return StreamingResponse(
        _generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get(
    "/status",
    summary="Get Camera Worker Status",
    description=(
        "Returns ``{ running, last_frame_at }``. ``last_frame_at`` is "
        "an ISO-8601 timestamp (UTC) or ``null`` if no frame has been "
        "captured yet."
    ),
)
def camera_status() -> dict:
    last = _worker.last_frame_at
    return {
        "running": _worker.running,
        "last_frame_at": last.isoformat() if last is not None else None,
    }


__all__ = [
    "CameraWorker",
    "router",
    "bind_worker_settings",
    "start_worker",
    "stop_worker",
]