"""Calibration test prints, generated from the machine's profile as
Marlin-style G-code (the G-code converter turns it into the machine's
NGC like any slicer file: heating, homing, ``E`` -> A, ``M186``).

* :func:`skew_square` — a square frame for XY skew: measure the
  diagonals AC, BD and the side AD (A front left, B front right, C back
  right, D back left — a solid tab inside corner A marks it).
* :func:`pa_tower` — a single-wall square tower whose pressure advance
  grows with the height (``SET_PRESSURE_ADVANCE`` every band): the
  height where the corners look best gives ``start + factor * height``.

And the results: :func:`skew_result`, :func:`pa_result`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Tuple

from core.skew import skew_factor

#: Retraction for travel moves (mm / mm/s).
RETRACT = 0.8
RETRACT_SPEED = 35.0
TRAVEL_SPEED = 150.0
FIRST_LAYER_SPEED = 25.0
#: Free border around a test print on the bed (mm).
BED_MARGIN = 15.0


@dataclass
class PrintSettings:
    hotend: float
    bed: float
    nozzle: float = 0.4
    filament: float = 1.75
    x_min: float = 0.0
    x_max: float = 200.0
    y_min: float = 0.0
    y_max: float = 200.0

    @property
    def layer(self) -> float:
        """~75 % of the nozzle, as Klipper's tuning prints."""
        return round(0.75 * self.nozzle, 2)

    @property
    def width(self) -> float:
        return round(1.125 * self.nozzle, 3)

    @property
    def centre(self) -> Tuple[float, float]:
        return (self.x_min + self.x_max) / 2.0, (self.y_min + self.y_max) / 2.0

    def largest(self, wanted: float) -> float:
        """``wanted`` mm, at most what fits the bed with a margin."""
        room = min(self.x_max - self.x_min, self.y_max - self.y_min) - 2 * BED_MARGIN
        if room < 20:
            raise ValueError(f"the bed ({self.x_max - self.x_min:g} × {self.y_max - self.y_min:g} mm) is too small")
        return min(float(wanted), room)


def settings_from_payload(payload: Mapping[str, Any], hotend: float, bed: float) -> PrintSettings:
    """The bed (X / Y travel), the nozzle and filament of the machine."""
    limits = {}
    for axis in payload.get("axes") or []:
        letter = str(axis.get("id", "")).lower()
        if letter in ("x", "y") and axis.get("position_max") is not None:
            limits[letter] = (float(axis.get("position_min") or 0.0), float(axis["position_max"]))
    if "x" not in limits or "y" not in limits:
        raise ValueError("the profile has no X / Y travel (position_max)")
    extruder = next((t for t in payload.get("tools") or [] if isinstance(t, dict) and t.get("type") == "extruder"), {})
    return PrintSettings(
        hotend=float(hotend), bed=float(bed),
        nozzle=float(extruder.get("nozzle_diameter") or 0.4),
        filament=float(extruder.get("filament_diameter") or 1.75),
        x_min=limits["x"][0], x_max=limits["x"][1], y_min=limits["y"][0], y_max=limits["y"][1],
    )


@dataclass
class _Writer:
    s: PrintSettings
    lines: List[str] = field(default_factory=list)
    x: Optional[float] = None
    y: Optional[float] = None
    z: float = 0.0
    retracted: bool = False

    def emit(self, line: str) -> None:
        self.lines.append(line)

    def e_for(self, length: float, width: float, height: float) -> float:
        area = math.pi * (self.s.filament / 2.0) ** 2
        return length * width * height / area

    def travel(self, x: float, y: float) -> None:
        if self.x is not None and math.hypot(x - self.x, y - (self.y or 0.0)) > 2.0 and not self.retracted:
            self.emit(f"G1 E-{RETRACT:g} F{RETRACT_SPEED * 60:g}")
            self.retracted = True
        self.emit(f"G0 X{x:.3f} Y{y:.3f} F{TRAVEL_SPEED * 60:g}")
        self.x, self.y = x, y

    def layer_z(self, z: float) -> None:
        self.z = z
        self.emit(f"G1 Z{z:.3f} F600")

    def extrude(self, x: float, y: float, speed: float, width: Optional[float] = None) -> None:
        if self.retracted:
            self.emit(f"G1 E{RETRACT:g} F{RETRACT_SPEED * 60:g}")
            self.retracted = False
        assert self.x is not None and self.y is not None
        length = math.hypot(x - self.x, y - self.y)
        e = self.e_for(length, width or self.s.width, self.s.layer)
        self.emit(f"G1 X{x:.3f} Y{y:.3f} E{e:.5f} F{speed * 60:g}")
        self.x, self.y = x, y

    def rectangle(self, x0: float, y0: float, x1: float, y1: float, speed: float) -> None:
        """A closed loop from (x0, y0), counter-clockwise."""
        self.travel(x0, y0)
        for x, y in ((x1, y0), (x1, y1), (x0, y1), (x0, y0)):
            self.extrude(x, y, speed)

    def fill(self, x0: float, y0: float, x1: float, y1: float, speed: float, along_x: bool) -> None:
        """Zigzag lines, one width apart."""
        w = self.s.width
        if along_x:
            lines = max(1, int((y1 - y0) / w))
            for k in range(lines):
                y = y0 + w / 2 + k * w
                a, b = (x0, x1) if k % 2 == 0 else (x1, x0)
                if k == 0:
                    self.travel(a, y)
                else:
                    self.extrude(a, y, speed)
                self.extrude(b, y, speed)
        else:
            lines = max(1, int((x1 - x0) / w))
            for k in range(lines):
                x = x0 + w / 2 + k * w
                a, b = (y0, y1) if k % 2 == 0 else (y1, y0)
                if k == 0:
                    self.travel(x, a)
                else:
                    self.extrude(x, a, speed)
                self.extrude(x, b, speed)

    def start(self, title: str) -> None:
        s = self.s
        self.lines += [
            f"; LinuxCNC_UI calibration print: {title}",
            f"; nozzle {s.nozzle:g} mm, filament {s.filament:g} mm, layer {s.layer:g} mm, width {s.width:g} mm",
            f"M140 S{s.bed:g}",
            f"M104 S{s.hotend:g}",
            "G28",
            f"M190 S{s.bed:g}",
            f"M109 S{s.hotend:g}",
            "G90",
            "M83",
            "G1 Z5 F600",
        ]
        # purge line along the front
        x0 = s.x_min + BED_MARGIN / 2
        y0 = s.y_min + BED_MARGIN / 3
        self.travel(x0, y0)
        self.layer_z(s.layer)
        self.extrude(min(x0 + 80.0, s.x_max - BED_MARGIN / 2), y0, FIRST_LAYER_SPEED, width=s.width * 1.5)
        self.emit("G1 E-0.8 F2100")
        self.retracted = True
        self.layer_z(s.layer + 0.6)

    def end(self, extra: Optional[List[str]] = None) -> None:
        self.lines += [
            f"G1 E-{RETRACT * 2:g} F{RETRACT_SPEED * 60:g}",
            "G91",
            "G1 Z10 F600",
            "G90",
            *(extra or []),
            "M104 S0",
            "M140 S0",
            "M107",
            "G28 X",
            "M2",
        ]


# --------------------------------------------------------------------------- #
# Skew                                                                         #
# --------------------------------------------------------------------------- #

def skew_square(s: PrintSettings, size: float = 100.0, height: float = 3.0, perimeters: int = 4) -> str:
    """A square frame, outer corners A (front left) B C D counter-clockwise,
    a solid tab inside corner A."""
    size = s.largest(size)
    cx, cy = s.centre
    x0, y0, x1, y1 = cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2
    w = s.width
    layers = max(3, round(height / s.layer))
    tab = min(12.0, size / 6)
    out = _Writer(s)
    out.start(f"skew square {size:g} mm")
    for n in range(layers):
        out.emit(f"; layer {n + 1}/{layers}")
        if n == 1:
            out.emit("M106 S255")
        out.layer_z(s.layer * (n + 1))
        speed = FIRST_LAYER_SPEED if n == 0 else 40.0
        for k in range(perimeters):  # outer first: the outer size is what is measured
            inset = w / 2 + k * w
            out.rectangle(x0 + inset, y0 + inset, x1 - inset, y1 - inset, speed)
        inner = perimeters * w
        out.fill(x0 + inner, y0 + inner, x0 + inner + tab, y0 + inner + tab, speed, along_x=n % 2 == 0)
    out.end()
    return "\n".join(out.lines) + "\n"


def skew_result(ac: float, bd: float, ad: float, printed_with: float) -> float:
    """The new factor: the skew measured on a print that already had
    ``printed_with`` applied, plus that."""
    return printed_with + skew_factor(ac, bd, ad)


# --------------------------------------------------------------------------- #
# Pressure advance                                                             #
# --------------------------------------------------------------------------- #

def pa_value(start: float, factor: float, height: float) -> float:
    return start + factor * height


def pa_tower(s: PrintSettings, size: float = 60.0, height: float = 40.0, start: float = 0.0,
             factor: float = 0.005, speed: float = 100.0, band: float = 1.0, restore: float = 0.0) -> str:
    """A single-wall square tower; pressure advance ``start + factor * z``
    set every ``band`` mm; ``restore`` is set again at the end."""
    size = s.largest(size)
    cx, cy = s.centre
    x0, y0, x1, y1 = cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2
    layers = max(5, round(height / s.layer))
    out = _Writer(s)
    out.start(f"pressure advance tower: {start:g} + {factor:g} per mm")
    out.emit(f"SET_PRESSURE_ADVANCE ADVANCE={start:.4f}")
    current_band = 0
    for n in range(layers):
        z = s.layer * (n + 1)
        out.emit(f"; layer {n + 1}/{layers}")
        out.layer_z(z)
        if n == 0:
            # a brim: three loops outside the wall, slowly
            for k in range(3, 0, -1):
                d = k * s.width
                out.rectangle(x0 - d, y0 - d, x1 + d, y1 + d, FIRST_LAYER_SPEED)
            out.rectangle(x0, y0, x1, y1, FIRST_LAYER_SPEED)
            continue
        if n == 1:
            out.emit("M106 S255")
        b = int(z // band)
        if b != current_band:
            current_band = b
            out.emit(f"SET_PRESSURE_ADVANCE ADVANCE={pa_value(start, factor, b * band):.4f}")
        out.rectangle(x0, y0, x1, y1, speed)
    out.end([f"SET_PRESSURE_ADVANCE ADVANCE={restore:.4f}"])
    return "\n".join(out.lines) + "\n"


def pa_result(start: float, factor: float, height: float) -> float:
    if height < 0:
        raise ValueError("the height cannot be negative")
    return round(pa_value(start, factor, height), 4)


__all__ = ["PrintSettings", "pa_result", "pa_tower", "pa_value", "settings_from_payload", "skew_result",
           "skew_square"]
