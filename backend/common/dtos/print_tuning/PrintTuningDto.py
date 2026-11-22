"""Print tuning (``PrintTuningService``): its HAL pins and its state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from dtos.pins.HalPin import HalPin


@dataclass(frozen=True, slots=True)
class PrintTuningPins:
    """``webgui.z-offset`` / ``flow`` / ``pressure-advance`` and one
    ``webgui.exclude-object-<n>`` per object a file may have."""
    z_offset: HalPin[float]
    flow: HalPin[float]
    pressure_advance: HalPin[float]
    exclude_objects: tuple[HalPin[bool], ...]


@dataclass(frozen=True, slots=True)
class PrintObjectDTO:
    index: int
    name: str
    excluded: bool


@dataclass(frozen=True, slots=True)
class PrintProgressDTO:
    percent: Optional[float]
    remaining_min: Optional[float]


@dataclass(frozen=True, slots=True)
class PrintTuningStateDTO:
    z_offset: float
    flow: float
    pressure_advance: float
    objects: tuple[PrintObjectDTO, ...] = ()
    progress: Optional[PrintProgressDTO] = None


__all__ = ["PrintObjectDTO", "PrintProgressDTO", "PrintTuningPins", "PrintTuningStateDTO"]
