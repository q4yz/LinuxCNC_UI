"""``[adxl345]`` on a CAN node -> ``webgui_connections.hal``: the machine
backend's record pin (``ResonanceService``) onto the sampler."""
from __future__ import annotations

from typing import Any

from .Adxl345HalMapper import SAMPLER, SIGNAL, Adxl345HalMapper


class Adxl345WebguiMapper:
    @staticmethod
    def to_lines(payload: dict[str, Any]) -> list[str]:
        if Adxl345HalMapper.node_adxl345(payload) is None:
            return []
        return [
            "# Accelerometer on the CAN node: recording for the resonance test",
            f"net {SIGNAL}-record webgui.accel-record => {SAMPLER}.enable",
            "",
        ]


__all__ = ["Adxl345WebguiMapper"]
