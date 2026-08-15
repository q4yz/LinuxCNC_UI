"""Tools module DTOs — re-exports for ergonomic imports.

Each concrete DTO lives in its own sibling module:

* :mod:`modules.tools.dtos.digital_spindle_dto` — digital VFD spindles.
* :mod:`modules.tools.dtos.analog_spindle_dto` — 0–10 V analog spindles.
* :mod:`modules.tools.dtos.extruder_dto` — heating tools
  (``extruder`` / ``heated_bed``).

The factory in :mod:`modules.tools.tool_halpin_factory` returns one of
those three concrete types; this package re-exports the class
objects so callers can write
``from modules.tools.dtos import HeaterPins`` without reaching into a
single-purpose module.
"""

from __future__ import annotations

from modules.tools.dtos.analog_spindle_dto import SpindleAnalogPins, SpindleAnalogStateDTO
from modules.tools.dtos.digital_spindle_dto import (
    SpindleDigitalPins,
    SpindleDigitalSettingsDTO,
    SpindleDigitalStateDTO,
)
from modules.tools.dtos.extruder_dto import HeaterPins, ExtruderPins, ExtruderStateDTO
from modules.tools.dtos.heater_dto import HeaterStateDTO

# Union of every concrete tool-pin record the factory can return.
# Used as the return-type annotation of ``ToolHalPinFactory.create``.
ToolPins = SpindleDigitalPins | SpindleAnalogPins | HeaterPins | ExtruderPins

ToolStateDTO =  SpindleDigitalStateDTO | SpindleAnalogStateDTO | HeaterStateDTO | ExtruderStateDTO


__all__ = [
    "HeaterPins",
    "SpindleAnalogPins",
    "SpindleDigitalPins",
    "SpindleDigitalSettingsDTO",
    "SpindleDigitalStateDTO",
    "ToolPins",
]
