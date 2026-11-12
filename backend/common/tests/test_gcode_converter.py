"""Marlin / slicer G-code -> LinuxCNC NGC (`core.gcode_converter`)."""
from __future__ import annotations

import pytest

from core.gcode_converter import convert, needs_conversion, ngc_name, read_prestart


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


@pytest.mark.parametrize("code", ["M84", "M400", "M201 X1000", "M73 P10 R2", "T0", "M900 K0"])
def test_commented_out(code):
    assert lines(code)[0].startswith(f"; {code}")


def test_start_gcode_g28_g29_run_before_the_program():
    out = lines("M190 S60\nG28\nG29\nG1 Z0.3\nG1 X0 Y20 E0.5\n")
    assert out[0] == "; LINUXCNC_UI_PRESTART: home level"
    assert read_prestart("\n".join(out)) == ["home", "level"]
    assert out[2].startswith("; G28") and "homing routine" in out[2]
    assert out[3].startswith("; G29") and "Z_TILT_ADJUST" in out[3]


def test_only_g28_lists_only_home():
    assert lines("G28 X Y\nG1 X1 Y1 E1\n")[0] == "; LINUXCNC_UI_PRESTART: home"
    assert read_prestart("G1 X1\n") == []


def test_g28_after_the_first_extrusion_parks():
    out = lines("G1 X1 Y1 E1\nG28 X\nG28 X0 Y0\nG28\nG29\n")
    assert out[1].startswith("o<g28> call [1] [0] [0]")
    assert out[2].startswith("o<g28> call [1] [1] [0]")
    assert out[3].startswith("o<g28> call [1] [1] [1]")
    assert out[4].startswith("; G29") and "not possible" in out[4]
    assert not out[0].startswith("; LINUXCNC_UI_PRESTART")


def test_z_only_extrusion_is_still_start_gcode():
    # A purge "G1 E5" without X/Y travel is not the print yet.
    assert lines("G1 E5\nG28\nG1 X1 Y1 E6\n")[0] == "; LINUXCNC_UI_PRESTART: home"


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
    notes = convert("G1 X1 Y1 E1\nG29\nM84\n").notes
    assert notes == ["line 2: 'G29' commented out", "line 3: M84 commented out"]


def test_names():
    assert ngc_name("part.gcode") == "part.ngc" and ngc_name("a/b.GCO") == "a/b.ngc"
    assert ngc_name("x.ngc") == "x.ngc"
    assert needs_conversion("part.gcode") and not needs_conversion("part.ngc")


def test_long_comment_line_is_cut_to_249_and_dots():
    from core.gcode_converter import MAX_LINE, convert

    line = "; " + "x" * 400
    out = convert(line + "\nM2\n").text.splitlines()
    assert out[0] == line[:249] + "..." and len(out[0]) == 252 == MAX_LINE
    exact = "; " + "y" * 250  # 252: kept as it is
    assert convert(exact + "\nM2\n").text.splitlines()[0] == exact
    one_over = "; " + "y" * 251  # 253: LinuxCNC already refuses it
    assert len(convert(one_over + "\nM2\n").text.splitlines()[0]) == 252


def test_converted_lines_fit_linuxcnc_line_buffer():
    # rs274ngc: fgets(line, LINELEN=255) fails when it reads 254 characters,
    # the "\n" included, so every line plus its newline must stay below 254
    from core.gcode_converter import convert

    text = "\n".join(["; " + "a" * 300, "G1 X1 ; " + "b" * 300, "G1 " + " ".join(f"X{k}" for k in range(80))])
    for line in convert(text + "\nM2\n").text.splitlines():
        assert len(line + "\n") < 254


def test_long_line_cut_inside_the_trailing_comment_keeps_the_code():
    from core.gcode_converter import convert

    out = convert("G1 X1 Y2 ; " + "c" * 300 + "\nM2\n").text.splitlines()[0]
    assert out.startswith("G1 X1 Y2 ;") and out.endswith("...") and len(out) == 252


def test_line_with_overlong_code_is_commented_out():
    from core.gcode_converter import convert

    result = convert("G1 " + " ".join(f"X{k}" for k in range(80)) + "\nM2\n")
    first = result.text.splitlines()[0]
    assert first.startswith("; G1 X0") and first.endswith("...") and len(first) <= 252
    assert any("longer than 252" in note for note in result.notes)
