"""WS2812 / SK6812 LED chains (``LedService``): their HAL pins and state."""
from __future__ import annotations

from dataclasses import dataclass

from dtos.pins.HalPin import HalPin


@dataclass(frozen=True, slots=True)
class LedPins:
    """One chain: its segments (``(first LED from 1, count)``) and one
    ``webgui.led-<id>-<k>`` float (0xRRGGBB) per segment."""
    id: str
    chain_count: int
    color_order: str
    segments: tuple[tuple[int, int], ...]
    pins: tuple[HalPin[float], ...]
    initial: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True, slots=True)
class LedSegmentDTO:
    first: int
    count: int
    red: float
    green: float
    blue: float


@dataclass(frozen=True, slots=True)
class LedStateDTO:
    id: str
    chain_count: int
    color_order: str
    segments: tuple[LedSegmentDTO, ...]


__all__ = ["LedPins", "LedSegmentDTO", "LedStateDTO"]
