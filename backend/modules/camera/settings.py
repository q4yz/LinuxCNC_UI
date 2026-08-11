"""Pydantic defaults schema for the camera module.

The schema documents the canonical shape the
:class:`core.settings_store.SettingsStore` will serve on
``GET /api/v1/modules/camera/settings``. New keys can be added in later
releases without breaking existing deployments — the store merges the
defaults underneath the persisted payload so a missing key is filled in
from this schema's defaults on every read.

Defaults here cover three groups of knobs:

* **MJPEG knobs** (``width`` / ``height`` / ``jpeg_quality`` /
  ``target_fps``) — the historical capture pipeline.
* **Source selection** (``default_device_id`` / ``ip_camera_url``) —
  introduced in Issue #56; the camera picked when the frontend does
  not pass ``?id=…`` and the optional IP-camera passthrough exposed
  through ``/devices``.
* **Per-camera operator preferences** (``preferences``) — a map keyed
  by device id (``/dev/videoN``, an OpenCV index, or the IP camera
  URL) holding the operator's rename / orientation / "hide from
  cycle" overrides. Persisted server-side so the rename follows the
  machine rather than the browser profile; the frontend used to keep
  this in ``window.localStorage`` and was migrated to the settings
  store for parity with the temperature module's pattern.
"""
from __future__ import annotations

from typing import Dict

from pydantic import BaseModel, Field


class CameraDevicePreference(BaseModel):
    """One row of operator overrides for a single camera.

    Keyed by the device id the backend returns from ``GET /devices``
    (``/dev/videoN``, an OpenCV index string, or the IP camera URL).
    All four fields are optional; an empty preference row means the
    operator has not touched that camera.
    """

    custom_name: str = Field(
        default="",
        description=(
            "Operator-chosen display name. Empty falls back to the "
            "hardware-reported name."
        ),
    )
    flip: bool = Field(
        default=False,
        description="Vertical mirror of the live feed.",
    )
    mirror: bool = Field(
        default=False,
        description="Horizontal mirror of the live feed.",
    )
    hidden: bool = Field(
        default=False,
        description=(
            "Skip this camera when cycling with the Switch Camera "
            "button. The device still appears in the Settings panel "
            "and can be picked manually."
        ),
    )


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
        preferences: Per-camera operator overrides keyed by device id.
            The frontend owns the read/write of this map; the streaming
            endpoints do not consume it. A device id that has no row
            behaves as if every field had its default value.
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
    preferences: Dict[str, CameraDevicePreference] = Field(
        default_factory=dict,
        description=(
            "Per-camera operator overrides keyed by device id. "
            "Persisted server-side alongside the MJPEG knobs so the "
            "rename follows the machine rather than the browser."
        ),
    )


__all__ = ["CameraSettings", "CameraDevicePreference"]
