"""``[neopixel NAME]`` -> ``webgui_connections.hal``: the machine backend's
colour per segment (``LedService``) onto its set point signal."""
from __future__ import annotations

from models.machineconfig.HardwareJsonModels import Led

from .LedHalMapper import LedHalMapper


class LedWebguiMapper:
    @staticmethod
    def to_lines(led: Led) -> list[str]:
        lines = [f"# LED: {led.id}"]
        for k in range(len(LedHalMapper.segments(led))):
            lines.append(f"net {LedHalMapper.segment_signal(led.id, k)} <= webgui.{LedHalMapper.segment_pin(led.id, k)}")
        return lines + [""]


__all__ = ["LedWebguiMapper"]
