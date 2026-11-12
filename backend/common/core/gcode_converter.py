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
* ``G28`` / ``G29`` in the start G-code (before the first extruding
  move) cannot run inside a LinuxCNC program (homing needs MANUAL mode,
  probing MDI): they are commented out and listed in a header line,
  ``; LINUXCNC_UI_PRESTART: home level``, which the machine backend runs
  when the program is started — the machine's homing routine
  (``[homing_override]``), then ``Z_TILT_ADJUST`` (``[z_tilt]``). A
  later ``G28 X`` (parking in the end G-code) becomes a move to the home
  position, ``o<g28> call [1] [0] [0]`` (``machine_config/m_codes/g28.ngc``,
  the positions from the INI's ``[UI_HOME]``); a later ``G29`` is
  commented out.
* Marlin's ``T<n>`` and every M-code LinuxCNC does not know are
  commented out with a note (LinuxCNC aborts the program on an unknown
  M-code).
* A line naming a macro — ``start 60 200``,
  ``PRINT_START BED=60 EXTRUDER=200`` — becomes
  ``o<start> call [60] [200]`` when ``macros/<name>.ngc`` exists
  (values in the order given); otherwise it is commented out.
* Klipper's ``SET_LED LED=sb RED=1 INDEX=2`` and Marlin's
  ``M150 R255 U0 B0 [W] [P<brightness>] [I<index>] [S<strip>]`` become
  ``M183 P<0xRRGGBB> Q<chain * 100 + LED>`` (``machine_config/m_codes/M183``;
  chain = the ``[neopixel]`` in declaration order, LED from 1, 0 = all)
  when the machine has LEDs; a ``SET_LED`` naming no LED is commented out.
* ``M2`` is appended when the file has no ``M2`` / ``M30``.
* A line longer than :data:`MAX_LINE` (252) characters is cut to its
  first 249 and ``...`` (LinuxCNC refuses longer lines). The cut always
  falls in a comment; a line whose *code* is that long is commented out
  instead (a cut move would still run, wrong).

``;`` comments (and the slicer's thumbnail blocks) pass through:
LinuxCNC reads ``;`` as a comment.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from core.led_color import encode, parse_set_led

#: Marlin codes the machine INI remaps to its own subroutines.
REMAPPED_MCODES = frozenset({104, 109, 140, 190, 106, 107})
#: M-codes LinuxCNC knows itself (M100-M199 are user M-codes) and that
#: mean the same in a slicer's file. ``M70``-``M73`` are left out on
#: purpose: in LinuxCNC they save/restore modal state, in Marlin ``M73``
#: is the print progress — commented out like any unknown code.
_LINUXCNC_MCODES = frozenset(
    {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 19, 30, 48, 49, 50, 51, 52, 53, 60, 61, 62, 63, 64, 65, 66, 67, 68}
)

#: The longest line LinuxCNC takes; a longer one is cut to
#: :data:`CUT_AT` characters and ``...``. rs274ngc reads a line with
#: ``fgets(line, LINELEN, ...)`` (``LINELEN`` = 255) and raises "Command
#: too long" once it got 254 characters — and those include the ``\n``.
MAX_LINE = 252
CUT_AT = MAX_LINE - 3

#: The header line listing what runs before the program (``read_prestart``).
PRESTART_MARKER = "; LINUXCNC_UI_PRESTART:"
#: Steps it may list, in the order they run.
PRESTART_STEPS = ("home", "level")

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
    printing: bool = False   # an extruding move was seen: start G-code is over
    prestart: list[str] = field(default_factory=list)
    leds: list[str] = field(default_factory=list)


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


def convert(text: str, macro_names: Iterable[str] = (), led_names: Sequence[str] = ()) -> ConversionResult:
    """Convert a whole file (see the module docstring). ``led_names``:
    the machine's ``[neopixel]`` names, in declaration order."""
    macros = {name.lower() for name in macro_names}
    state = _State(leds=[name.lower() for name in led_names])
    out: list[str] = []
    notes: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line, note = _convert_line(raw.rstrip("\r"), state, macros)
        line, cut_note = _limit_length(line)
        note = note or cut_note
        out.append(line)
        if note:
            notes.append(f"line {number}: {note}")
    if not state.has_end:
        out.append("M2  ; [added: LinuxCNC needs a program end]")
    if state.prestart:
        steps = [s for s in PRESTART_STEPS if s in state.prestart]
        out.insert(0, f"{PRESTART_MARKER} {' '.join(steps)}")
    return ConversionResult(text="\n".join(out) + "\n", notes=notes)


def _limit_length(line: str) -> tuple[str, str | None]:
    """``line`` cut to :data:`MAX_LINE` (see the module docstring)."""
    if len(line) <= MAX_LINE:
        return line, None
    code, _comment = _split_comment(line)
    if len(code.rstrip()) <= CUT_AT:
        return line[:CUT_AT] + "...", None
    return "; " + line[:CUT_AT - 2] + "...", f"longer than {MAX_LINE} characters: commented out"


def read_prestart(head: str) -> list[str]:
    """The steps a converted file asks to run before it starts (its
    first lines), ``[]`` for any other file."""
    for line in head.splitlines()[:5]:
        if line.startswith(PRESTART_MARKER):
            return [s for s in line[len(PRESTART_MARKER):].split() if s in PRESTART_STEPS]
    return []


def _convert_line(raw: str, state: _State, macros: set[str]) -> tuple[str, str | None]:
    code, comment = _split_comment(raw)
    stripped = code.strip()
    if not stripped:
        return raw, None
    upper = stripped.upper()

    if upper.startswith("SET_LED"):
        return _set_led(stripped, state, comment)

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
        return _home_or_level(stripped, words, state, comment)
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
        if m == 150 and state.leds:
            return _m150(words, comment), None
        if m not in _LINUXCNC_MCODES and not 100 <= m <= 199:
            return _commented(stripped, "not a LinuxCNC M-code", comment), f"M{m} commented out"
        return raw, None

    if "E" in letters:
        return _extrude(code, words, state, comment), None
    return raw, None


def _home_or_level(stripped: str, words: list[tuple[str, str]], state: _State, comment: str) -> tuple[str, str | None]:
    leveling = any(letter == "G" and float(v) == 29 for letter, v in words)
    if not state.printing:
        step = "level" if leveling else "home"
        if step not in state.prestart:
            state.prestart.append(step)
        what = "Z_TILT_ADJUST" if leveling else "the homing routine"
        return _commented(stripped, f"runs before the program: {what}", comment), None
    if leveling:
        return _commented(stripped, "leveling mid-program: not possible", comment), f"{stripped!r} commented out"
    # "G28 X" carries a bare letter (no number), so read the letters.
    axes = {c for c in stripped.upper() if c in "XYZ"} or {"X", "Y", "Z"}
    flags = " ".join(f"[{int(a in axes)}]" for a in "XYZ")
    return f"o<g28> call {flags}  ; {stripped} -> to the home position" + (f" {comment}" if comment else ""), None


def _led_call(color: int, chain: int, index: int, comment: str) -> str:
    return f"M183 P{color} Q{chain * 100 + index}" + (f"  {comment}" if comment else "")


def _set_led(stripped: str, state: _State, comment: str) -> tuple[str, str | None]:
    try:
        command = parse_set_led(stripped)
    except ValueError as exc:
        return _commented(stripped, str(exc), comment), f"{stripped!r}: {exc}"
    if command is None:
        return _commented(stripped, "not a command", comment), None
    if command.led not in state.leds:
        return _commented(stripped, f"no LED '{command.led}'", comment), f"{stripped!r}: no [neopixel {command.led}]"
    color = encode(command.red, command.green, command.blue, command.white)
    return _led_call(color, state.leds.index(command.led), command.index or 0, comment), None


def _m150(words: list[tuple[str, str]], comment: str) -> str:
    """Marlin ``M150 R U B W`` (0-255), ``P`` brightness, ``I`` LED (from
    0), ``S`` strip."""
    values = {letter: float(v) for letter, v in words if letter != "M"}
    scale = values.get("P", 255.0) / 255.0 / 255.0
    color = encode(values.get("R", 0) * scale, values.get("U", 0) * scale,
                   values.get("B", 0) * scale, values.get("W", 0) * scale)
    index = int(values["I"]) + 1 if "I" in values and values["I"] >= 0 else 0
    return _led_call(color, int(values.get("S", 0)), index, comment)


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
    if delta > 0 and any(letter in "XY" for letter, _ in words):
        state.printing = True
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


__all__ = [
    "PRESTART_MARKER", "PRESTART_STEPS", "REMAPPED_MCODES", "ConversionResult",
    "convert", "needs_conversion", "ngc_name", "read_prestart",
]
