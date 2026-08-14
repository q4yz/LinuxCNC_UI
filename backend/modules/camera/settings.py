"""Pydantic defaults schema for the camera module.

The schema documents the canonical shape the
:class:`core.settings_store.SettingsStore` will serve on
``GET /api/v1/modules/camera/settings``. New keys can be added in later
releases without breaking existing deployments — the store merges the
defaults underneath the persisted payload so a missing key is filled in
from this schema's defaults on every read.

The previous schema carried four MJPEG knobs (``width`` / ``height`` /
``jpeg_quality`` / ``target_fps``) used by the OpenCV-based capture
loop. The camera module now delegates the stream to ``ustreamer`` — a
pure-C MJPEG server we spawn as a subprocess per detected device. The
resolution, framerate, and encoder quality are now CLI flags on the
supervisor and not user-tunable from the settings panel; the schema
no longer persists them.

Two groups of knobs survive:

* **Source selection** (``default_device_id`` / ``ip_camera_url``) —
  introduced in Issue #56; the camera picked when the frontend does
  not pass ``?id=…`` and the optional IP-camera passthrough exposed
  through ``/devices``.
* **Per-camera operator preferences** (``preferences``) — a map keyed
  by device id (``/dev/videoN``, the IP camera URL) holding the
  operator's rename / orientation / "hide from cycle" overrides.
  Persisted server-side so the rename follows the machine rather than
  the browser profile; the frontend used to keep this in
  ``window.localStorage`` and was migrated to the settings store for
  parity with the temperature module's pattern.
"""
from __future__ import annotations

from typing import Dict

from pydantic import BaseModel, Field


class CameraDevicePreference(BaseModel):
    """One row of operator overrides for a single camera.

    Keyed by the device id the backend returns from ``GET /devices``
    (``/dev/videoN`` or the IP camera URL). All four fields are
    optional; an empty preference row means the operator has not
    touched that camera.
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
    """User-tunable knobs for the camera module.

    Attributes:
        default_device_id: Camera source used by ``GET /stream`` when
            no ``?id=`` query parameter is supplied. Typically a
            ``/dev/videoN`` path or an HTTP/RTSP URL.
        ip_camera_url: Optional pass-through camera source. When set,
            it is exposed as a synthetic row in ``GET /devices`` with
            ``source == "ip"`` so the Vue picker can include it.
        preferences: Per-camera operator overrides keyed by device id.
            The frontend owns the read/write of this map; the streaming
            endpoints do not consume it. A device id that has no row
            behaves as if every field had its default value.
    """

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
            "Persisted server-side alongside the source selection so "
            "the rename follows the machine rather than the browser."
        ),
    )


__all__ = ["CameraSettings", "CameraDevicePreference"]
