"""``[adxl345]`` on a CAN node -> ``webgui_connections.hal``: the machine
backend's record pin (``ResonanceService``) onto the sampler."""
from __future__ import annotations

from models.machineconfig.HardwareJsonModels import Adxl345

from .Adxl345HalMapper import SAMPLER, SIGNAL, Adxl345HalMapper


class Adxl345WebguiMapper:
    @staticmethod
    def to_lines(adxl: Adxl345 | None) -> list[str]:
        if not Adxl345HalMapper.on_node(adxl):
            return []
        return [
            "# Accelerometer on the CAN node: recording for the resonance test",
            f"net {SIGNAL}-record webgui.accel-record => {SAMPLER}.enable",
            "",
        ]


__all__ = ["Adxl345WebguiMapper"]
