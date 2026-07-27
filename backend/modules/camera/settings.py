"""Pydantic defaults schema for the camera module.

The schema documents the canonical shape the
:class:`core.settings_store.SettingsStore` will serve on
``GET /api/v1/modules/camera/settings``. New keys can be added in later
releases without breaking existing deployments — the store merges the
defaults underneath the persisted payload so a missing key is filled in
from this schema's defaults on every read.

Defaults here cover both the historical MJPEG knobs (resolution,
JPEG quality, target FPS) and the on-demand streaming knobs introduced
in Issue #56: ``default_device_id`` (the camera picked when the
frontend does not pass ``?id=…``) and ``ip_camera_url`` (an optional
HTTP/RTSP feed exposed through ``/devices``).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CameraSettings(BaseModel):
    """User-tunable knobs for the USB webcam MJPEG stream.

    Attributes:
        width:  Negotiated capture width in pixels. Bounded to common
            webcam resolutions so the store rejects obviously bad input.
        height: Negotiated capture height in pixels.
        jpeg_quality: Quality parameter passed to ``cv2.IMWRITE_JPEG_QUALITY``.
            Higher = better quality, larger payload. Bounded to the
            ``1-100`` range the OpenCV encoder accepts.
        target_fps: Cap on the client-side stream framerate. The
            generator sleeps for ``1 / target_fps`` seconds per frame so
            the asyncio event loop keeps breathing for jog keep-alives.
        default_device_id: Camera source used by ``GET /stream`` when
            no ``?id=`` query parameter is supplied. Typically a
            ``/dev/videoN`` path on Linux or an HTTP/RTSP URL.
        ip_camera_url: Optional pass-through camera source. When set,
            it is exposed as a synthetic row in ``GET /devices`` with
            ``source == "ip"`` so the Vue picker can include it.
    """

    width: int = Field(default=640, ge=160, le=3840, description="Capture width in pixels.")
    height: int = Field(default=480, ge=120, le=2160, description="Capture height in pixels.")
    jpeg_quality: int = Field(default=70, ge=10, le=100, description="JPEG encoder quality (10-100).")
    target_fps: int = Field(default=15, ge=1, le=60, description="Cap on stream framerate.")
    default_device_id: str = Field(
        default="",
        description=(
            "Camera source used by /stream when no ?id= query param is "
            "supplied. /dev/videoN path or HTTP/RTSP URL. Empty on "
            "first boot."
        ),
    )
    ip_camera_url: str = Field(
        default="",
        description=(
            "Optional IP-camera URL surfaced through /devices. "
            "Empty means no IP camera entry."
        ),
    )


__all__ = ["CameraSettings"]