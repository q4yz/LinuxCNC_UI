"""Tools module DTOs — re-exports for ergonomic imports.

Each concrete DTO lives in its own sibling module:

* :mod:`dtos.tools.digital_spindle_dto` — digital VFD spindles.
* :mod:`dtos.tools.analog_spindle_dto` — 0–10 V analog spindles.
* :mod:`dtos.tools.extruder_dto` — heating tools
  (``extruder`` / ``heated_bed``).

The factory in :mod:`modules.tools.tool_halpin_factory` returns one of
those three concrete types; this package re-exports the class
objects so callers can write
``from dtos.tools import HeaterPins`` without reaching into a
single-purpose module.
"""

from __future__ import annotations

from dtos.tools.SpindleAnalogDto import SpindleAnalogPins, SpindleAnalogStateDTO
from dtos.tools.SpindleDigitalDto import (
    SpindleDigitalPins,
    SpindleDigitalSettingsDTO,
    SpindleDigitalStateDTO,
)
from dtos.tools.ExtruderDto import HeaterPins, ExtruderPins, ExtruderStateDTO
from dtos.tools.HeaterDto import HeaterStateDTO

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
