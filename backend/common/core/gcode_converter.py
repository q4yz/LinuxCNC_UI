"""Marlin / slicer G-code -> LinuxCNC NGC (`.agent/component/gcode_upload.md`).

A slicer writes G-code for Marlin/Klipper; LinuxCNC rejects much of it
(no ``E`` axis, unknown M-codes, ``G28`` meaning "go to stored
position"). Every uploaded ``.gcode`` file is converted line by line:

* ``E`` -> ``A`` (the extruder axis), always as an **absolute** A: the
  converter tracks ``M82`` / ``M83`` / ``G90`` / ``G91`` / ``G92 E`` and
  writes the running total, so no ``G92`` offset is ever set. Under
  ``G91`` the A delta is written, like X/Y/Z.
* ``M104 / M109 / M140 / M190 / M106 / M107`` keep their number (user
  M-code programs in ``machine_config/m_codes/``: LinuxCNC cannot REMAP
  M100-M199, ``marlin_mcodes``), Marlin's
  ``S`` / ``R`` (value) and ``T`` / ``P`` (heater / fan index) become
  ``P`` and ``Q``: ``M104 S200 T1`` -> ``M104 P200 Q1``. A bare ``M106``
  (full speed) is written ``M106 P255``. An ``M106`` / ``M107`` for a
  part fan the machine does not have (``part_fans``; the program would
  fail there: "this machine has no part fan") is commented out.
  :func:`convert_mdi` does the same for a line typed in MDI.
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
* Firmware retraction: a bare ``G10`` / ``G11`` (no ``L``: that is a
  LinuxCNC offset) becomes the ``[firmware_retraction]`` move on A
  (``retraction``); without one it is commented out.
* ``M221 S<%>`` (flow) -> ``M184 P<%>``; ``SET_GCODE_OFFSET Z=`` /
  ``Z_ADJUST=`` -> ``M185 P<mm> Q0`` / ``Q1`` (the live Z offset). Both
  are user M-codes (``machine_config/m_codes``).
* ``M900 K<k>`` / ``SET_PRESSURE_ADVANCE ADVANCE=<k>`` -> ``M186 P<k>``
  (pressure advance, a user M-code).
* ``M600`` (filament change) stays: the machine REMAPs it (``m600.ngc``).
* A filament unit (``tool_slots``, the ACE Pro's 4): the slicer's tool
  change ``T<n>`` (and the ACE drivers' ``ACE_CHANGE_TOOL TOOL=<n>``)
  becomes ``M640 P<n>`` — REMAPped to ``ace_change.ngc`` (LinuxCNC's own
  ``T0`` means "no tool"). Without one ``T<n>`` is commented out.
* Objects (Klipper's ``EXCLUDE_OBJECT_START NAME=`` / ``_END``, Marlin's
  ``M486 S<n>`` / ``S-1``, slicer comments ``; printing object`` /
  ``; stop printing object``, ``; OBJECT_ID:`` and Cura's ``;MESH:<name>`` /
  ``;MESH:NONMESH``): each object's part of
  a layer is wrapped in ``o<exclude_N> if [#<_hal[webgui.exclude-object-K]>
  GT 0]`` — an excluded object skips its moves (its other lines still
  run) and sets A to where the moves would have left it (``G92 A``). The
  objects are listed in a header line, ``; LINUXCNC_UI_OBJECTS: [...]``
  (``read_objects``); at most :data:`MAX_OBJECTS`. A file with objects or
  ``M600`` / ``M640`` starts with ``G92.1`` (an earlier print's A offset
  cleared).
* A line longer than :data:`MAX_LINE` (252) characters is cut to its
  first 249 and ``...`` (LinuxCNC refuses longer lines). The cut always
  falls in a comment; a line whose *code* is that long is commented out
  instead (a cut move would still run, wrong).

``;`` comments (and the slicer's thumbnail blocks) pass through:
LinuxCNC reads ``;`` as a comment.
"""
from __future__ import annotations

from models.machineconfig.HardwareJsonModels import FirmwareRetraction

import json
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

#: The header line listing the file's objects, index = HAL pin number.
OBJECTS_MARKER = "; LINUXCNC_UI_OBJECTS:"
#: The header line with the area the print extrudes in (adaptive bed mesh).
BOUNDS_MARKER = "; LINUXCNC_UI_BOUNDS:"

#: Objects that can be excluded (``webgui.exclude-object-0`` ... ``-31``).
MAX_OBJECTS = 32

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
    part_fans: int | None = None  # None: not known, every fan line kept
    retraction: FirmwareRetraction | None = None  # [firmware_retraction]
    retracted: bool = False
    feed: float | None = None  # the file's last F (restored after a retraction)
    uses_m600: bool = False  # M600 / M640: they set A with G92
    tool_slots: int | None = None  # a filament unit's slots: T<n> -> M640 P<n>
    objects: list[str] = field(default_factory=list)
    x: float | None = None  # the XY position (absolute moves)
    y: float | None = None
    bounds: list[float] | None = None  # xmin, ymin, xmax, ymax of the extruding moves


def _split_comment(line: str) -> tuple[str, str]:
    """``(code, comment)``; the comment keeps its leading ``;``."""
    index = line.find(";")
    if index < 0:
        return line, ""
    return line[:index], line[index:]


def _commented(code: str, reason: str, comment: str) -> str:
    return f"; {code.strip()}  ; [{reason}]{(' ' + comment) if comment else ''}"


def _words(code: str) -> list[tuple[str, str]]:
    # upper-cased once: the letters come out upper case, the numbers unchanged
    return _WORD.findall(code.upper())


def convert(
    text: str, macro_names: Iterable[str] = (), led_names: Sequence[str] = (), part_fans: int | None = None,
    retraction: FirmwareRetraction | None = None, tool_slots: int | None = None,
) -> ConversionResult:
    """Convert a whole file (see the module docstring). ``led_names``:
    the machine's ``[neopixel]`` names, in declaration order;
    ``part_fans``: how many part fans ``M106`` / ``M107`` can reach
    (``None``: unknown, every fan line is kept); ``retraction``: the
    machine's ``[firmware_retraction]``; ``tool_slots``: a filament unit's
    slots (``T<n>`` -> ``M640 P<n>``), ``None`` without one."""
    macros = {name.lower() for name in macro_names}
    state = _State(leds=[name.lower() for name in led_names], part_fans=part_fans, retraction=retraction,
                   tool_slots=tool_slots)
    out: list[str] = []
    notes: list[str] = []
    block: dict[str, int] | None = None  # the open object block: start index in out, object index
    label = 0

    def close_block() -> None:
        nonlocal block, label
        if block is None:
            return
        start, index = block["start"], block["index"]
        block = None
        body = out[start:]
        if not any(_is_move(line) for line in body):
            return
        label += 1
        name = f"o<exclude_{label}>"
        skip = [line for line in body if not _is_move(line) and _split_comment(line)[0].strip()]
        if not state.xyz_relative:
            skip.append(f"G92 A{_fmt(state.a_total)}  ; [excluded object: A as if it had been printed]")
        if state.feed is not None:
            skip.append(f"F{_fmt(state.feed)}  ; [excluded object: its last feed rate]")
        out[start:] = [
            f"{name} if [#<_hal[webgui.exclude-object-{index}]> GT 0]  ; [object {state.objects[index]!r} excluded]",
            *skip,
            f"{name} else",
            *body,
            f"{name} endif",
        ]

    for number, raw in enumerate(text.splitlines(), start=1):
        raw = raw.rstrip("\r")
        # split and parsed once per line; the helpers below share it
        code, comment = _split_comment(raw)
        marker, object_name = _object_marker(raw, code)
        if marker in ("start", "end", "boundary"):
            close_block()
        if marker == "start" and object_name is not None:
            if object_name not in state.objects:
                if len(state.objects) < MAX_OBJECTS:
                    state.objects.append(object_name)
                else:
                    notes.append(f"line {number}: more than {MAX_OBJECTS} objects: {object_name!r} cannot be excluded")
            if object_name in state.objects:
                block = {"start": len(out) + 1, "index": state.objects.index(object_name)}
        if marker in ("start", "end", "define"):
            out.append(f"; {raw.strip()}" if code.strip() else raw)
            continue
        words = _words(code)
        move = bool(words) and bool(_MOVE.match(code))
        _track_feed(words, move, state)
        line, note = _convert_line(raw, state, macros, (code, comment, words))
        _track_position(words, move, state)
        line, cut_note = _limit_length(line)
        note = note or cut_note
        out.append(line)
        if note:
            notes.append(f"line {number}: {note}")
    close_block()
    if not state.has_end:
        out.append("M2  ; [added: LinuxCNC needs a program end]")
    if state.objects:
        out.insert(0, f"{OBJECTS_MARKER} {json.dumps(state.objects)}")
    if state.bounds is not None:
        out.insert(0, f"{BOUNDS_MARKER} " + " ".join(_fmt(v) for v in state.bounds))
    if state.objects or state.uses_m600:
        out.insert(0, "G92.1  ; [added: clears an earlier print's A offset (filament change, excluded objects)]")
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


def read_objects(head: str) -> list[str]:
    """The objects of a converted file (its header line), index = the
    ``webgui.exclude-object-<index>`` pin; ``[]`` for any other file."""
    for line in head.splitlines()[:5]:
        if line.startswith(OBJECTS_MARKER):
            try:
                value = json.loads(line[len(OBJECTS_MARKER):])
            except ValueError:
                return []
            return [str(v) for v in value] if isinstance(value, list) else []
    return []


_MOVE = re.compile(r"^\s*(?:N\d+\s*)?G0*[0-3](?![0-9.])", re.IGNORECASE)
_LAYER_BOUNDARY = re.compile(
    r"^\s*;\s*(?:LAYER_CHANGE|CHANGE_LAYER|LAYER:|MACHINE_END_GCODE_START|EXECUTABLE_BLOCK_END|END_PRINT|End of Gcode)",
    re.IGNORECASE,
)
_OBJECT_START_COMMENTS = (
    re.compile(r"^\s*;\s*printing object\s+(.+?)\s*$", re.IGNORECASE),
    re.compile(r"^\s*;\s*OBJECT_ID:\s*(\S+)", re.IGNORECASE),
    re.compile(r"^\s*;\s*MESH:(.+?)\s*$", re.IGNORECASE),  # Cura
)
_OBJECT_END_COMMENT = re.compile(r"^\s*;\s*(?:stop printing object|MESH:NONMESH\s*$)", re.IGNORECASE)
_KLIPPER_NAME = re.compile(r"NAME\s*=\s*(\S+)", re.IGNORECASE)


def _is_move(line: str) -> bool:
    return bool(_MOVE.match(_split_comment(line)[0]))


def _object_marker(raw: str, code: str | None = None) -> tuple[str | None, str | None]:
    """``("start", name)``, ``("end", None)``, ``("define", None)`` (an
    object marker line, not converted), ``("boundary", None)`` (a layer
    change / the end G-code: ends an object block, the line stays) or
    ``(None, None)``. ``code``: the line without its comment, if split."""
    code = (_split_comment(raw)[0] if code is None else code).strip()
    if code and code[0] in "Gg":
        return None, None  # a move: the common case, no marker
    upper = code.upper()
    if upper.startswith("EXCLUDE_OBJECT_START"):
        match = _KLIPPER_NAME.search(code)
        return ("start", match.group(1)) if match else ("define", None)
    if upper.startswith("EXCLUDE_OBJECT_END"):
        return "end", None
    if upper.startswith("EXCLUDE_OBJECT"):
        return "define", None  # EXCLUDE_OBJECT_DEFINE, EXCLUDE_OBJECT NAME= (runtime)
    m486 = re.match(r"^M0*486\b(.*)$", upper)
    if m486:
        value = dict(_words(code))
        if "S" in value:
            number = int(float(value["S"]))
            return ("end", None) if number < 0 else ("start", str(number))
        return "define", None  # M486 T<count>, A<name>
    if code:
        if upper.split()[0] in ("M2", "M02", "M30"):
            return "boundary", None
        return None, None
    if _OBJECT_END_COMMENT.match(raw):
        return "end", None
    for pattern in _OBJECT_START_COMMENTS:
        match = pattern.match(raw)
        if match:
            name = match.group(1).strip()
            name = re.sub(r"\s+id:\s*\d+.*$", "", name, flags=re.IGNORECASE).strip() or name
            return "start", name
    if _LAYER_BOUNDARY.match(raw):
        return "boundary", None
    return None, None


def read_bounds(head: str) -> tuple[float, float, float, float] | None:
    """The area a converted file extrudes in, ``(xmin, ymin, xmax, ymax)``;
    ``None`` for any other file."""
    for line in head.splitlines()[:6]:
        if line.startswith(BOUNDS_MARKER):
            try:
                x0, y0, x1, y1 = (float(v) for v in line[len(BOUNDS_MARKER):].split())
            except ValueError:
                return None
            return x0, y0, x1, y1
    return None


def _grow_bounds(state: _State, x: float, y: float) -> None:
    if state.bounds is None:
        state.bounds = [x, y, x, y]
    else:
        b = state.bounds
        b[0], b[1], b[2], b[3] = min(b[0], x), min(b[1], y), max(b[2], x), max(b[3], y)


def _track_position(words: list[tuple[str, str]], move: bool, state: _State) -> None:
    """The XY position after an absolute G0-G3 (relative moves lose it)."""
    if not move:
        return
    values = dict(words)
    if state.xyz_relative:
        state.x = state.y = None
        return
    if "X" in values:
        state.x = float(values["X"])
    if "Y" in values:
        state.y = float(values["Y"])


def _track_feed(words: list[tuple[str, str]], move: bool, state: _State) -> None:
    """Remember the file's feed rate (a G0-G3 / bare F line's F)."""
    feed = None
    for letter, value in words:
        if letter == "M" or (letter == "G" and not move):
            return
        if letter == "F":
            feed = value
    if feed is not None:
        state.feed = float(feed)


def _retraction(stripped: str, state: _State, comment: str, unretract: bool) -> tuple[str, str | None]:
    """A bare ``G10`` / ``G11``: the ``[firmware_retraction]`` move on A."""
    config = state.retraction
    length = config.retract_length if config is not None else 0.0
    if config is None or length <= 0:
        return _commented(stripped, "firmware retraction: no [firmware_retraction]", comment), \
            f"{stripped!r}: no [firmware_retraction] retract_length"
    if unretract != state.retracted:
        return _commented(stripped, "already " + ("unretracted" if unretract else "retracted"), comment), None
    if unretract:
        delta = length + config.unretract_extra_length
        speed = config.unretract_speed
    else:
        delta = -length
        speed = config.retract_speed
    state.retracted = not unretract
    state.a_total += delta
    a = delta if state.xyz_relative else state.a_total
    line = f"G1 A{_fmt(a)} F{_fmt(speed * 60)}  ; [{stripped}: firmware retraction]" + (f" {comment}" if comment else "")
    if state.feed is not None:
        line += f"\nF{_fmt(state.feed)}  ; [the file's feed rate again]"
    return line, None


def _gcode_offset(stripped: str, comment: str) -> tuple[str, str | None]:
    """Klipper's ``SET_GCODE_OFFSET Z=`` / ``Z_ADJUST=`` -> ``M185``."""
    params = {k.upper(): v for k, v in re.findall(r"([A-Za-z_]+)\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+))", stripped)}
    if "Z_ADJUST" in params:
        return f"M185 P{_fmt(float(params['Z_ADJUST']))} Q1" + (f"  {comment}" if comment else ""), None
    if "Z" in params:
        return f"M185 P{_fmt(float(params['Z']))} Q0" + (f"  {comment}" if comment else ""), None
    return _commented(stripped, "only Z / Z_ADJUST", comment), f"{stripped!r}: only Z / Z_ADJUST"


def read_prestart(head: str) -> list[str]:
    """The steps a converted file asks to run before it starts (its
    first lines), ``[]`` for any other file."""
    for line in head.splitlines()[:5]:
        if line.startswith(PRESTART_MARKER):
            return [s for s in line[len(PRESTART_MARKER):].split() if s in PRESTART_STEPS]
    return []


def _convert_line(raw: str, state: _State, macros: set[str],
                  parsed: tuple[str, str, list[tuple[str, str]]] | None = None) -> tuple[str, str | None]:
    """``parsed``: (code, comment, words) when the caller split it already."""
    code, comment = (parsed[0], parsed[1]) if parsed is not None else _split_comment(raw)
    stripped = code.strip()
    if not stripped:
        return raw, None
    upper = stripped.upper()
    # A G-code word (G1 X…, the bulk of a print) is no keyword, macro or M117.
    if not (upper[0] == "G" and _WORD.match(stripped)):
        special = _special_line(stripped, upper, state, comment, macros)
        if special is not None:
            return special
    return _convert_words(raw, code, stripped, comment, state,
                          parsed[2] if parsed is not None else _words(stripped))


def _tool_change(stripped: str, tool: str | None, state: _State, comment: str) -> tuple[str, str | None]:
    """``T<n>`` -> ``M640 P<n>`` on a machine with a filament unit."""
    if not state.tool_slots:
        return _commented(stripped, "extruder select: one extruder", comment), None
    try:
        slot = int(float(tool or ""))
    except ValueError:
        return _commented(stripped, "tool change without a number", comment), None
    if not 0 <= slot < state.tool_slots:
        return _commented(stripped, f"no slot {slot}: the filament unit has {state.tool_slots}", comment), \
            f"T{slot} commented out (no such slot)"
    state.uses_m600 = True
    return f"M640 P{slot}" + (f"  {comment}" if comment else ""), None


def _special_line(stripped: str, upper: str, state: _State, comment: str,
                  macros: set[str]) -> tuple[str, str | None] | None:
    """Klipper keywords, a macro call, M117 — ``None`` for anything else."""
    if upper.startswith("ACE_CHANGE_TOOL"):
        tool = re.search(r"TOOL\s*=\s*(-?\d+)", stripped, re.IGNORECASE)
        return _tool_change(stripped, tool.group(1) if tool else None, state, comment)
    if upper.startswith("SET_LED"):
        return _set_led(stripped, state, comment)
    if upper.startswith("SET_GCODE_OFFSET"):
        return _gcode_offset(stripped, comment)
    if upper.startswith("SET_PRESSURE_ADVANCE"):
        value = re.search(r"ADVANCE\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+))", stripped, re.IGNORECASE)
        if value is None:
            return _commented(stripped, "only ADVANCE=", comment), None
        return f"M186 P{_fmt(float(value.group(1)))}" + (f"  {comment}" if comment else ""), None

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
    return None


def _convert_words(raw: str, code: str, stripped: str, comment: str, state: _State,
                   words: list[tuple[str, str]]) -> tuple[str, str | None]:
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
    if gcodes and gcodes[0] in (10, 11) and "L" not in letters:
        return _retraction(stripped, state, comment, unretract=gcodes[0] == 11)
    if 4 in gcodes:
        return _dwell(words, comment), None
    if "T" in letters and not mcodes and not gcodes:
        return _tool_change(stripped, dict(words).get("T"), state, comment)

    if mcodes:
        m = int(mcodes[0])
        if m == 82:
            state.e_relative = False
            return _commented(stripped, "absolute E: handled by the converter", comment), None
        if m == 83:
            state.e_relative = True
            return _commented(stripped, "relative E: handled by the converter", comment), None
        if m in (106, 107) and state.part_fans is not None:
            fan = _fan_index(words)
            if fan is None or fan >= state.part_fans:
                reason = ("this machine has no part fan" if state.part_fans == 0 or fan is None
                          else f"no part fan {fan} on this machine")
                return _commented(stripped, reason, comment), f"M{m} commented out: {reason}"
        if m in REMAPPED_MCODES:
            return _remapped(m, words, comment), None
        if m == 150 and state.leds:
            return _m150(words, comment), None
        if m == 221:
            percent = dict(words).get("S")
            if percent is None:
                return _commented(stripped, "M221 without S", comment), None
            return f"M184 P{percent}" + (f"  {comment}" if comment else ""), None
        if m == 900:  # Marlin linear advance K: pressure advance
            k = dict(words).get("K")
            if k is None:
                return _commented(stripped, "M900 without K", comment), None
            return f"M186 P{k}" + (f"  {comment}" if comment else ""), None
        if m == 600:
            state.uses_m600 = True
            return "M600" + (f"  {comment}" if comment else ""), None
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


_MARLIN_MDI = re.compile(r"^\s*M0*(104|106|107|109|140|190|221|900)(?![0-9.])", re.IGNORECASE)


def convert_mdi(line: str) -> str:
    """A Marlin heater / fan code typed in MDI, ``M104 S200 T1``, as the
    user M-code takes it, ``M104 P200 Q1``; every other line, and one
    already in ``P`` / ``Q`` form (no ``S`` / ``R`` / ``T``), unchanged."""
    match = _MARLIN_MDI.match(line)
    if match is None:
        return line
    code, comment = _split_comment(line)
    words = _words(code)
    m = int(match.group(1))
    letters = [letter for letter, _ in words]
    if m == 900:  # Marlin linear advance: the pressure advance M-code
        k = dict(words).get("K")
        return line if k is None else f"M186 P{k}" + (f"  {comment}" if comment else "")
    # M107's only word is the fan: Marlin's P is the user M-code's Q.
    if not any(letter in "SRT" for letter in letters) and not (m == 107 and "P" in letters):
        return line
    if letters.count("M") != 1:
        return line  # another M-code on the line: leave it to LinuxCNC
    if m == 221:  # flow: the M184 user M-code
        percent = dict(words).get("S")
        return line if percent is None else f"M184 P{percent}" + (f"  {comment}" if comment else "")
    return _remapped(m, words, comment)


def _fan_index(words: list[tuple[str, str]]) -> int | None:
    """Marlin's fan index (``P``, default 0); ``None`` when it is not one."""
    raw = dict(words).get("P", "0")
    try:
        value = float(raw)
    except ValueError:
        return None
    return int(value) if value >= 0 and value == int(value) else None


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
    if m == 106 and value is None:
        value = "255"  # Marlin: M106 without S is full speed
    if value is not None and m != 107:
        parts.append(f"P{value}")
    if index is not None:
        parts.append(f"Q{index}")
    return " ".join(parts) + (f"  {comment}" if comment else "")


_E_WORD = re.compile(r"[Ee]\s*[-+]?(?:\d+\.?\d*|\.\d+)")


def _extrude(code: str, words: list[tuple[str, str]], state: _State, comment: str) -> str:
    values = dict(words)
    e = float(values["E"])
    delta = e if state.e_relative else e - state.e_position
    state.e_position = state.e_position + delta if state.e_relative else e
    state.a_total += delta
    if delta > 0 and any(letter in "XY" for letter, _ in words):
        state.printing = True
        # the area of the print: the move's start and end (absolute moves)
        if not state.xyz_relative and state.x is not None and state.y is not None:
            _grow_bounds(state, state.x, state.y)
            _grow_bounds(state, float(values.get("X", state.x)), float(values.get("Y", state.y)))
    a = delta if state.xyz_relative else state.a_total
    converted = _E_WORD.sub(f"A{_fmt(a)}", code, count=1)
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
    "convert_mdi", "read_bounds", "read_objects", "OBJECTS_MARKER", "MAX_OBJECTS", "PRESTART_MARKER", "PRESTART_STEPS", "REMAPPED_MCODES", "ConversionResult",
    "convert", "needs_conversion", "ngc_name", "read_prestart",
]
