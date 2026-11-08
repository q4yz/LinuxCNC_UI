"""Marlin / slicer G-code -> LinuxCNC NGC (`.agent/component/gcode_upload.md`).

A slicer writes G-code for Marlin/Klipper; LinuxCNC rejects much of it
(no ``E`` axis, unknown M-codes, ``G28`` meaning "go to stored
position"). Every uploaded ``.gcode`` file is converted line by line:

* ``E`` -> ``A`` (the extruder axis), always as an **absolute** A: the
  converter tracks ``M82`` / ``M83`` / ``G90`` / ``G91`` / ``G92 E`` and
  writes the running total, so no ``G92`` offset is ever set. Under
  ``G91`` the A delta is written, like X/Y/Z.
* ``M104 / M109 / M140 / M190 / M106 / M107`` keep their number (the
  machine's INI remaps them, `ini_template_generator`), Marlin's
  ``S`` / ``R`` (value) and ``T`` / ``P`` (heater / fan index) become
  ``P`` and ``Q``: ``M104 S200 T1`` -> ``M104 P200 Q1``.
* ``G4 S2`` -> ``G4 P2``; ``G4 P500`` (Marlin: ms) -> ``G4 P0.5``.
* ``M117 text`` -> ``(MSG, text)``.
* ``G28`` / ``G29``, Marlin's ``T<n>``, and every M-code LinuxCNC does
  not know are commented out with a note (LinuxCNC aborts the program
  on an unknown M-code; homing has to happen before a program).
* A line naming a macro — ``start 60 200``,
  ``PRINT_START BED=60 EXTRUDER=200`` — becomes
  ``o<start> call [60] [200]`` when ``macros/<name>.ngc`` exists
  (values in the order given); otherwise it is commented out.
* ``M2`` is appended when the file has no ``M2`` / ``M30``.

``;`` comments (and the slicer's thumbnail blocks) pass through:
LinuxCNC reads ``;`` as a comment.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

#: Marlin codes the machine INI remaps to its own subroutines.
REMAPPED_MCODES = frozenset({104, 109, 140, 190, 106, 107})
#: M-codes LinuxCNC knows itself (M100-M199 are user M-codes) and that
#: mean the same in a slicer's file. ``M70``-``M73`` are left out on
#: purpose: in LinuxCNC they save/restore modal state, in Marlin ``M73``
#: is the print progress — commented out like any unknown code.
_LINUXCNC_MCODES = frozenset(
    {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 19, 30, 48, 49, 50, 51, 52, 53, 60, 61, 62, 63, 64, 65, 66, 67, 68}
)

_WORD = re.compile(r"([A-Za-z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
_MACRO_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\s+(.*))?$")
_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)")


def _fmt(value: float) -> str:
    text = f"{value:.5f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


@dataclass
class ConversionResult:
    text: str
    #: One note per line that was changed in meaning or commented out.
    notes: list[str] = field(default_factory=list)


@dataclass
class _State:
    xyz_relative: bool = False
    e_relative: bool = False
    e_position: float = 0.0  # E in the file's own coordinates
    a_total: float = 0.0     # the absolute A written so far
    has_end: bool = False


def _split_comment(line: str) -> tuple[str, str]:
    """``(code, comment)``; the comment keeps its leading ``;``."""
    index = line.find(";")
    if index < 0:
        return line, ""
    return line[:index], line[index:]


def _commented(code: str, reason: str, comment: str) -> str:
    return f"; {code.strip()}  ; [{reason}]{(' ' + comment) if comment else ''}"


def _words(code: str) -> list[tuple[str, str]]:
    return [(letter.upper(), value) for letter, value in _WORD.findall(code)]


def convert(text: str, macro_names: Iterable[str] = ()) -> ConversionResult:
    """Convert a whole file (see the module docstring)."""
    macros = {name.lower() for name in macro_names}
    state = _State()
    out: list[str] = []
    notes: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line, note = _convert_line(raw.rstrip("\r"), state, macros)
        out.append(line)
        if note:
            notes.append(f"line {number}: {note}")
    if not state.has_end:
        out.append("M2  ; [added: LinuxCNC needs a program end]")
    return ConversionResult(text="\n".join(out) + "\n", notes=notes)


def _convert_line(raw: str, state: _State, macros: set[str]) -> tuple[str, str | None]:
    code, comment = _split_comment(raw)
    stripped = code.strip()
    if not stripped:
        return raw, None
    upper = stripped.upper()

    # A macro call: a word that is no G-code letter+number, then values.
    macro = _MACRO_LINE.match(stripped)
    if macro and not _WORD.match(stripped):
        name = macro.group(1).lower()
        args = _NUMBER.findall(macro.group(2) or "")
        if name in macros:
            call = f"o<{name}> call" + "".join(f" [{a}]" for a in args)
            return call + (f"  {comment}" if comment else ""), None
        return _commented(stripped, f"no macro '{name}'", comment), f"{stripped!r}: no macro {name}.ngc"

    if upper.startswith("M117"):
        message = stripped[4:].strip().replace("(", "[").replace(")", "]")
        return f"(MSG, {message})" + (f"  {comment}" if comment else ""), None

    words = _words(stripped)
    if not words:
        return raw, None
    letters = {letter for letter, _ in words}
    gcodes = [float(v) for letter, v in words if letter == "G"]
    mcodes = [float(v) for letter, v in words if letter == "M"]

    for g in gcodes:
        if g == 90:
            state.xyz_relative, state.e_relative = False, False
        elif g == 91:
            state.xyz_relative, state.e_relative = True, True
    for m in mcodes:
        if m in (2, 30):
            state.has_end = True

    if any(g in (28, 29) for g in gcodes):
        return _commented(stripped, "homing / leveling: run it before the program", comment), f"{stripped!r} commented out"
    if 92 in gcodes:
        return _g92(stripped, words, state, comment)
    if 4 in gcodes:
        return _dwell(words, comment), None
    if "T" in letters and not mcodes and not gcodes:
        return _commented(stripped, "extruder select: one extruder", comment), None

    if mcodes:
        m = int(mcodes[0])
        if m == 82:
            state.e_relative = False
            return _commented(stripped, "absolute E: handled by the converter", comment), None
        if m == 83:
            state.e_relative = True
            return _commented(stripped, "relative E: handled by the converter", comment), None
        if m in REMAPPED_MCODES:
            return _remapped(m, words, comment), None
        if m not in _LINUXCNC_MCODES and not 100 <= m <= 199:
            return _commented(stripped, "not a LinuxCNC M-code", comment), f"M{m} commented out"
        return raw, None

    if "E" in letters:
        return _extrude(code, words, state, comment), None
    return raw, None


def _g92(stripped: str, words: list[tuple[str, str]], state: _State, comment: str) -> tuple[str, str | None]:
    values = dict(words)
    others = [f"{letter}{v}" for letter, v in words if letter in "XYZ"]
    if "E" in values:
        state.e_position = float(values["E"])
    if others:
        # A real G92 on X/Y/Z stays (rare in slicer output); E never does.
        return "G92 " + " ".join(others) + (f"  {comment}" if comment else ""), None
    return _commented(stripped, "E reset: handled by the converter", comment), None


def _dwell(words: list[tuple[str, str]], comment: str) -> str:
    values = dict(words)
    if "S" in values:
        seconds = float(values["S"])
    elif "P" in values:
        seconds = float(values["P"]) / 1000.0  # Marlin: P in ms
    else:
        seconds = 0.0
    return f"G4 P{_fmt(seconds)}" + (f"  {comment}" if comment else "")


def _remapped(m: int, words: list[tuple[str, str]], comment: str) -> str:
    """``M104 S200 T1`` -> ``M104 P200 Q1``; fans: ``M106 S255 P1`` -> ``M106 P255 Q1``."""
    values = dict(words)
    value = values.get("S") or values.get("R")
    if m in (106, 107):
        index = values.get("P")
    else:
        index = values.get("T")
        value = value if value is not None else values.get("P")
    parts = [f"M{m}"]
    if value is not None and m != 107:
        parts.append(f"P{value}")
    if index is not None:
        parts.append(f"Q{index}")
    return " ".join(parts) + (f"  {comment}" if comment else "")


def _extrude(code: str, words: list[tuple[str, str]], state: _State, comment: str) -> str:
    e = float(dict(words)["E"])
    delta = e if state.e_relative else e - state.e_position
    state.e_position = state.e_position + delta if state.e_relative else e
    state.a_total += delta
    a = delta if state.xyz_relative else state.a_total
    converted = re.sub(r"[Ee]\s*[-+]?(?:\d+\.?\d*|\.\d+)", f"A{_fmt(a)}", code, count=1)
    return converted.rstrip() + (f"  {comment}" if comment else "")


def ngc_name(filename: str) -> str:
    """``part.gcode`` -> ``part.ngc`` (other names unchanged)."""
    lower = filename.lower()
    for ext in (".gcode", ".gco", ".g"):
        if lower.endswith(ext):
            return filename[: -len(ext)] + ".ngc"
    return filename


def needs_conversion(filename: str) -> bool:
    return ngc_name(filename) != filename


__all__ = ["REMAPPED_MCODES", "ConversionResult", "convert", "needs_conversion", "ngc_name"]
