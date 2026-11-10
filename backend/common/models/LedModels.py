"""LED chain state (``[neopixel]``, `.agent/component/neopixel.md`):
``GET``/``PUT /api/v1/leds`` and the base-thread snapshot's ``leds``."""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class LedSegment(BaseModel):
    first: int = Field(..., description="First LED of the segment (from 1).")
    count: int = Field(..., description="LEDs in the segment.")
    red: float = Field(..., ge=0.0, le=1.0)
    green: float = Field(..., ge=0.0, le=1.0)
    blue: float = Field(..., ge=0.0, le=1.0)


class Led(BaseModel):
    id: str
    chain_count: int
    color_order: str
    segments: List[LedSegment]


__all__ = ["Led", "LedSegment"]
