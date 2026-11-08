"""Marlin / slicer G-code -> LinuxCNC NGC (`core.gcode_converter`)."""
from __future__ import annotations

import pytest

from core.gcode_converter import convert, needs_conversion, ngc_name


def lines(text, macros=()):
    return convert(text, macros).text.splitlines()


def test_extrusion_becomes_absolute_a():
    out = lines("G90\nM82\nG92 E0\nG1 X10 E1.5 F1500\nG1 X20 E3\nG92 E0\nG1 E-0.8\nM83\nG1 X30 E0.5\nG1 E-0.4\n")
    moves = [l for l in out if l.startswith("G1")]
    assert moves == ["G1 X10 A1.5 F1500", "G1 X20 A3", "G1 A2.2", "G1 X30 A2.7", "G1 A2.3"]
    assert not any(l.startswith("G92") for l in out)  # no offset ever set


def test_relative_moves_write_the_delta():
    out = lines("G91\nG1 X1 E0.5\nG1 E0.25\nG90\nG1 X5 E2\n")
    assert [l for l in out if l.startswith("G1")] == ["G1 X1 A0.5", "G1 A0.25", "G1 X5 A2"]


def test_g92_keeps_xyz():
    assert "G92 Z0.2" in lines("G92 Z0.2 E0\n")


@pytest.mark.parametrize(
    ("marlin", "linuxcnc"),
    [
        ("M104 S215 T0", "M104 P215 Q0"),
        ("M109 R200", "M109 P200"),
        ("M140 S60", "M140 P60"),
        ("M190 S60", "M190 P60"),
        ("M106 S255", "M106 P255"),
        ("M106 S128 P1", "M106 P128 Q1"),
        ("M107", "M107"),
        ("M107 P1", "M107 Q1"),
        ("G4 S2", "G4 P2"),
        ("G4 P500", "G4 P0.5"),
        ("M117 Layer (1)", "(MSG, Layer [1])"),
    ],
)
def test_translated(marlin, linuxcnc):
    assert lines(marlin)[0] == linuxcnc


@pytest.mark.parametrize("code", ["G28", "G28 X Y", "G29", "M84", "M400", "M201 X1000", "M73 P10 R2", "T0", "M900 K0"])
def test_commented_out(code):
    assert lines(code)[0].startswith(f"; {code}")


def test_linuxcnc_mcodes_pass():
    for code in ("M3 S1000", "M5", "M0", "M62 P0", "M150"):
        assert lines(code)[0] == code


def test_macro_calls():
    out = lines("start 60 215\nPRINT_START BED=60 EXTRUDER=215\nend\n", ["start", "print_start"])
    assert out[:2] == ["o<start> call [60] [215]", "o<print_start> call [60] [215]"]
    assert out[2].startswith("; end") and "no macro" in out[2]


def test_comments_and_thumbnails_pass_through():
    src = "; thumbnail begin 16x16 100\n; iVBORw0KGgo=\n; thumbnail end\nG1 X1 E1 ; first\n"
    out = lines(src)
    assert out[:3] == src.splitlines()[:3]
    assert out[3] == "G1 X1 A1  ; first"


def test_program_end():
    assert lines("G1 X1\n")[-1].startswith("M2")
    assert lines("G1 X1\nM30\n")[-1] == "M30"


def test_notes():
    notes = convert("G28\nM84\n").notes
    assert notes == ["line 1: 'G28' commented out", "line 2: M84 commented out"]


def test_names():
    assert ngc_name("part.gcode") == "part.ngc" and ngc_name("a/b.GCO") == "a/b.ngc"
    assert ngc_name("x.ngc") == "x.ngc"
    assert needs_conversion("part.gcode") and not needs_conversion("part.ngc")
