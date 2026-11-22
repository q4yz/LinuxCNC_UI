"""Bed mesh compensation on / off (``BedMeshService``): its pin and state."""
from __future__ import annotations

from dataclasses import dataclass

from dtos.pins.HalPin import HalPin


@dataclass(frozen=True, slots=True)
class BedMeshPins:
    """``webgui.bed-mesh-enable`` -> ``compensation.enable-in``."""
    enable: HalPin[bool]


@dataclass(frozen=True, slots=True)
class BedMeshStateDTO:
    enabled: bool


__all__ = ["BedMeshPins", "BedMeshStateDTO"]
