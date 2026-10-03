"""Camera source selection, as the machine backend's camera supervisor
reads it.

Both values are central UI settings owned by the system service
(``camera.default_device_id`` / ``camera.ip_camera_url``, see
``core/ui_settings_store.py``). The supervisor reads them by key on
every request (``core/ui_settings_reader.py``) and builds this model,
whose defaults apply when a key was never set. Per-camera display
preferences are UI-only and never reach the backend.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CameraSettings(BaseModel):
    """Camera source selection.

    Attributes:
        default_device_id: Camera source used by ``GET /stream`` when
            no ``?id=`` query parameter is supplied. Typically a
            ``/dev/videoN`` path or an HTTP/RTSP URL.
        ip_camera_url: Optional pass-through camera source. When set,
            it is exposed as a synthetic row in ``GET /devices`` with
            ``source == "ip"`` so the Vue picker can include it.
    """

    default_device_id: str = Field(
        default="",
        description="Camera source used by /stream when no ?id= is given. Empty = first detected.",
    )
    ip_camera_url: str = Field(
        default="",
        description="Optional IP-camera URL surfaced through /devices. Empty = no IP camera.",
    )


__all__ = ["CameraSettings"]
