"""LED colours and Klipper's ``SET_LED`` (`.agent/component/neopixel.md`),
shared by the machine backend (sets them) and the upload converter.

A segment's colour travels as one float, 0xRRGGBB (exact: a float has a
24-bit mantissa), the Remora "RGB" module's set point. Klipper's
``WHITE`` has no channel of its own there: an RGBW chip's white LED is
taken from the colour by the firmware (W = min(R, G, B)), so white is
added to R, G and B.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


def encode(red: float, green: float, blue: float, white: float = 0.0) -> int:
    """0-1 channels -> 0xRRGGBB (white folded into R, G, B)."""
    def byte(value: float) -> int:
        return max(0, min(255, round((value + white) * 255)))

    return (byte(red) << 16) | (byte(green) << 8) | byte(blue)


def decode(color: float) -> tuple[float, float, float]:
    value = max(0, min(0xFFFFFF, int(round(color or 0))))
    return ((value >> 16) & 0xFF) / 255.0, ((value >> 8) & 0xFF) / 255.0, (value & 0xFF) / 255.0


@dataclass(frozen=True)
class SetLed:
    """One ``SET_LED`` command."""

    led: str
    red: float = 0.0
    green: float = 0.0
    blue: float = 0.0
    white: float = 0.0
    index: Optional[int] = None  # LED number from 1; None: the whole chain


_PARAM = re.compile(r"([A-Za-z_]+)\s*=\s*(\S+)")


def parse_set_led(line: str) -> Optional[SetLed]:
    """``SET_LED LED=sb RED=1 GREEN=0.5 INDEX=2`` -> :class:`SetLed`;
    ``None`` for any other line. ``TRANSMIT`` / ``SYNC`` are accepted
    and ignored (every change is sent at once). Raises ``ValueError``
    for a ``SET_LED`` without ``LED`` or with a bad value."""
    text = line.split(";", 1)[0].strip()
    if not text.upper().startswith("SET_LED"):
        return None
    if len(text) > 7 and not text[7].isspace():
        return None
    params = {key.upper(): value for key, value in _PARAM.findall(text[7:])}
    led = params.get("LED")
    if not led:
        raise ValueError("SET_LED needs LED=<name>")
    try:
        channels = {
            name: float(params.get(name.upper(), 0.0)) for name in ("red", "green", "blue", "white")
        }
        index = int(params["INDEX"]) if "INDEX" in params else None
    except ValueError as exc:
        raise ValueError(f"SET_LED: {exc}") from exc
    for name, value in channels.items():
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"SET_LED: {name.upper()} {value:g} is outside 0.0 ... 1.0")
    if index is not None and index < 1:
        raise ValueError("SET_LED: INDEX counts from 1")
    return SetLed(led=led.lower(), index=index, **channels)


__all__ = ["SetLed", "decode", "encode", "parse_set_led"]
