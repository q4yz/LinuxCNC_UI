"""``[z_tilt]`` -> ``webgui_connections.hal``: the machine backend's
per-motor targets (``ZTiltService``) onto the offset ramps."""
from __future__ import annotations

from typing import Any

from .ZTiltHalMapper import ZTiltHalMapper


class ZTiltWebguiMapper:
    """The machine backend's target pin per motor onto its ramp."""

    @staticmethod
    def to_lines(z_tilt: dict[str, Any]) -> list[str]:
        lines = ["# Z tilt: per-motor offset targets"]
        for k in range(len(z_tilt.get("joints") or [])):
            lines.append(f"net ztilt-{k}-target webgui.{ZTiltHalMapper.target_pin(k)} => {ZTiltHalMapper.ramp_name(k)}.in")
        return lines + [""]


__all__ = ["ZTiltWebguiMapper"]
