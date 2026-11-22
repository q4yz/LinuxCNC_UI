"""``[neopixel NAME]`` -> ``webgui_connections.hal``: the machine backend's
colour per segment (``LedService``) onto its set point signal."""
from __future__ import annotations

from typing import Any

from .LedHalMapper import LedHalMapper


class LedWebguiMapper:
    @staticmethod
    def to_lines(led: dict[str, Any]) -> list[str]:
        led_id = str(led["id"])
        lines = [f"# LED: {led_id}"]
        for k in range(len(led.get("segments") or [[1, 1]])):
            lines.append(f"net {LedHalMapper.segment_signal(led_id, k)} <= webgui.{LedHalMapper.segment_pin(led_id, k)}")
        return lines + [""]


__all__ = ["LedWebguiMapper"]
