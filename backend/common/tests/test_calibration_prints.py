"""Calibration test prints: valid for the converter, the right size and
pressure advance steps, and the results' math."""
from __future__ import annotations

import math
import re

import pytest

from core.calibration_prints import (PrintSettings, pa_result, pa_tower, settings_from_payload, skew_result,
                                     skew_square)
from core.gcode_converter import convert

PAYLOAD = {
    "axes": [{"id": "x", "position_min": 0, "position_max": 235}, {"id": "y", "position_min": 0, "position_max": 235},
             {"id": "z", "position_max": 250}],
    "tools": [{"id": "e", "type": "extruder", "nozzle_diameter": 0.4, "filament_diameter": 1.75}],
}


def _settings():
    return settings_from_payload(PAYLOAD, 210, 60)


def _xy(lines, extruding=True):
    pts = []
    for line in lines:
        m = re.match(r"G1 X([-\d.]+) Y([-\d.]+) E([-\d.]+)", line)
        if m and extruding:
            pts.append((float(m.group(1)), float(m.group(2))))
    return pts


def test_settings_from_the_profile():
    s = _settings()
    assert (s.nozzle, s.filament, s.layer, s.width, s.centre) == (0.4, 1.75, 0.3, 0.45, (117.5, 117.5))
    with pytest.raises(ValueError, match="X / Y"):
        settings_from_payload({}, 210, 60)


def test_skew_square_is_the_size_asked_and_converts():
    text = skew_square(_settings(), size=100)
    pts = _xy(text.splitlines())
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    # the purge line is at the front; the frame's outer edge is 100 mm (the outer line's centre w/2 inside)
    frame = [(x, y) for x, y in pts if y > 20]
    fx, fy = [p[0] for p in frame], [p[1] for p in frame]
    assert max(fx) - min(fx) == pytest.approx(100 - 0.45, abs=1e-3)
    assert max(fy) - min(fy) == pytest.approx(100 - 0.45, abs=1e-3)
    assert min(xs) >= 0 and max(xs) <= 235 and min(ys) >= 0
    result = convert(text)
    out = result.text
    assert "; LINUXCNC_UI_PRESTART: home" in out and " A" in out and "M109 P210" in out
    assert not re.search(r"^G1 [^;]*E", out, re.M), "E must become A"
    assert not any("unknown" in n.lower() for n in result.notes), result.notes


def test_skew_square_fits_a_small_bed():
    small = PrintSettings(210, 60, x_max=120, y_max=120)
    pts = [p for p in _xy(skew_square(small, size=100).splitlines()) if p[1] > 10]
    assert max(p[0] for p in pts) - min(p[0] for p in pts) < 120 - 2 * 15 + 1e-6


def test_pa_tower_steps_the_advance_and_restores_it():
    text = pa_tower(_settings(), size=60, height=10, start=0.0, factor=0.01, band=1.0, restore=0.04)
    values = [float(v) for v in re.findall(r"SET_PRESSURE_ADVANCE ADVANCE=([\d.]+)", text)]
    assert values[0] == 0.0 and values[-1] == 0.04
    steps = values[1:-1]
    # 33 layers of 0.3 mm: the top (9.9 mm) is in band 9
    assert steps == sorted(steps) and steps[0] == pytest.approx(0.01) and steps[-1] == pytest.approx(0.09)
    out = convert(text).text
    assert "M186 P0.0400" in out or "M186 P0.04" in out


@pytest.mark.parametrize("s", [0.0, 0.004, -0.007])
def test_skew_math_on_a_simulated_machine(s):
    """A machine whose X drifts by s per mm Y prints the square as a
    parallelogram; the measured diagonals give s back."""
    L = 100.0
    A, B, C, D = (0, 0), (L, 0), (L + s * L, L), (s * L, L)
    dist = lambda p, q: math.hypot(p[0] - q[0], p[1] - q[1])
    assert skew_result(dist(A, C), dist(B, D), dist(A, D), printed_with=0.0) == pytest.approx(s, abs=1e-9)
    # printed with a correction f0 already: the residual is s - f0, the new factor s again
    f0 = 0.002
    r = s - f0
    A, B, C, D = (0, 0), (L, 0), (L + r * L, L), (r * L, L)
    assert skew_result(dist(A, C), dist(B, D), dist(A, D), printed_with=f0) == pytest.approx(s, abs=1e-9)


def test_pa_result():
    assert pa_result(0.0, 0.005, 12.5) == 0.0625
    with pytest.raises(ValueError):
        pa_result(0, 0.005, -1)
