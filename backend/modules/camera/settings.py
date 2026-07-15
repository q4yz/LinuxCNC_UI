"""Pydantic defaults schema for the camera module.

The schema documents the canonical shape the
:class:`core.settings_store.SettingsStore` will serve on
``GET /api/v1/modules/camera/settings``. New keys can be added in later
releases without breaking existing deployments — the store merges the
defaults underneath the persisted payload so a missing key is filled in
from this schema's defaults on every read.

The defaults here match the hard-coded values that used to live in
``routers/camera.py`` (640x480 @ 15 fps, JPEG quality 70, device index
0). Migrating them out of the source into this schema is what makes the
module user-configurable without touching the router code.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CameraSettings(BaseModel):
    """User-tunable knobs for the USB webcam MJPEG stream.

    Attributes:
        device_index: ``cv2.VideoCapture`` device index. ``0`` is the
            first V4L2 device; bump to ``1``/``2``/… for additional
            cameras.
        width:  Negotiated capture width in pixels. Bounded to common
            webcam resolutions so the store rejects obviously bad input.
        height: Negotiated capture height in pixels.
        jpeg_quality: Quality parameter passed to ``cv2.IMWRITE_JPEG_QUALITY``.
            Higher = better quality, larger payload. Bounded to the
            ``1-100`` range the OpenCV encoder accepts.
        target_fps: Cap on the client-side stream framerate. The worker
            sleeps for ``1 / target_fps`` seconds per frame so the
            asyncio event loop keeps breathing for jog keep-alives.
    """

    device_index: int = Field(default=0, ge=0, description="cv2.VideoCapture device index.")
    width: int = Field(default=640, ge=160, le=3840, description="Capture width in pixels.")
    height: int = Field(default=480, ge=120, le=2160, description="Capture height in pixels.")
    jpeg_quality: int = Field(default=70, ge=10, le=100, description="JPEG encoder quality (10-100).")
    target_fps: int = Field(default=15, ge=1, le=60, description="Cap on stream framerate.")


__all__ = ["CameraSettings"]