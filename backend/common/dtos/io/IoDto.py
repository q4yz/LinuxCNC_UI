"""Fans, ``[output_pin]`` outputs and ``[input_pin]`` inputs (``IoService``):
their HAL pins and their state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from dtos.pins.HalPin import HalPin


@dataclass(frozen=True, slots=True)
class IoOutputPins:
    """``webgui.<id>``; a latched output (an input sets it) also has
    ``webgui.<id>-set`` (toggled per UI event) and ``-state`` (the result)."""
    id: str
    pin: HalPin[Any]
    pwm: bool = False
    scale: float = 1.0
    start_value: float = 0.0
    latch_set: Optional[HalPin[bool]] = None
    latch_state: Optional[HalPin[float]] = None


@dataclass(frozen=True, slots=True)
class IoInputPins:
    id: str
    pin: HalPin[bool]


@dataclass(frozen=True, slots=True)
class IoPins:
    outputs: tuple[IoOutputPins, ...] = ()
    inputs: tuple[IoInputPins, ...] = ()


@dataclass(frozen=True, slots=True)
class IoFanDTO:
    id: str
    value: float


@dataclass(frozen=True, slots=True)
class IoOutputDTO:
    id: str
    pwm: bool
    scale: float
    value: float


@dataclass(frozen=True, slots=True)
class IoInputDTO:
    id: str
    value: bool


@dataclass(frozen=True, slots=True)
class IoStateDTO:
    fans: tuple[IoFanDTO, ...] = ()
    outputs: tuple[IoOutputDTO, ...] = ()
    inputs: tuple[IoInputDTO, ...] = ()


__all__ = ["IoFanDTO", "IoInputDTO", "IoInputPins", "IoOutputDTO", "IoOutputPins", "IoPins", "IoStateDTO"]
