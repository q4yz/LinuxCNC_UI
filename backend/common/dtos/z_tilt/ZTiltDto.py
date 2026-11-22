"""Z tilt adjust (``ZTiltService``): its pins and state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from dtos.pins.HalPin import HalPin


@dataclass(frozen=True, slots=True)
class ZTiltPins:
    """``webgui.ztilt-<k>``: the target offset of Z motor k (mm)."""
    offsets: tuple[HalPin[float], ...] = ()


@dataclass(frozen=True, slots=True)
class ZTiltStateDTO:
    configured: bool
    running: bool
    offsets: tuple[float, ...] = ()
    spread: Optional[float] = None


__all__ = ["ZTiltPins", "ZTiltStateDTO"]
