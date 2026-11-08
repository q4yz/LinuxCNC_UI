"""``machine.ini`` renderer.

Unlike the earlier, fully-commented skeleton, this renders a
**live** INI: every section LinuxCNC needs to actually load a
configuration is populated with either a known-good default (lifted
from a real, working PrintNC machine — see
``machine_config/example/PrintNC-WEBGUI``) or a value derived from
the source profile's ``.cfg`` limits via :class:`AxisBuilder`. The
goal is "it compiles and LinuxCNC can start it" — not "it's a fully
tuned, ready-to-cut machine". Kinematics are assumed ``trivkins``
(see :mod:`.generator`); an axis can still drive more than one joint
(e.g. a dual-motor gantry axis), which is why ``coordinates=`` can
repeat a letter (``XYYZ``) and ``[KINS] JOINTS`` counts joints, not
axis letters.
"""

from __future__ import annotations

from typing import Any, Dict, List

from domain_file_services import paths
from mappers.machineconfig import heater_ini_section

from models.machineconfig.LinuxCNCModels import Axis

#: Documented defaults for PID fields no schema carries yet — see
#: `.agent/component/heater.md` § 1 (`pid_on_measurement` defaults to
#: true) and `HeaterHalMapper`'s own `_DEFAULT_MAX_POWER` (the same
#: 100% ceiling, so the HAL and INI sides agree even though neither
#: reads it from a real field today).
_DEFAULT_PID_PONM = 1
_DEFAULT_PID_CVMAX = 100.0

#: `[AXIS_Z] OFFSET_AV_RATIO` — the fraction of the axis's own
#: velocity/acceleration budget LinuxCNC's trajectory planner reserves
#: for *external offset* motion (`axis.z.eoffset-*`,
#: `PauseInspectWebguiMapper`). Undeclared (LinuxCNC's own default is
#: 0), the eoffset stage has zero motion budget and never actually
#: moves the axis no matter what `eoffset-counts` is set to — a
#: silent no-op, not an error, so nothing else catches it. Every
#: machine gets `PauseInspectWebguiMapper`'s Z eoffset wiring
#: unconditionally, so every machine's `[AXIS_Z]` needs this too, or
#: the feature is wired but inert. 0.2 is a conservative default
#: (verified against a real machine) — 20% of Z's own velocity/accel
#: ceiling reserved for the lift, leaving 80% for normal G-code motion.
_OFFSET_AV_RATIO = 0.2

#: ``[input_pin]`` edge subroutines, next to machine.ini (relative paths
#: in ``SUBROUTINE_PATH`` are resolved from the INI's folder).
SUBROUTINES_DIR = "subroutines"

#: PrintNC-WEBGUI's known-good ``[DISPLAY]`` block (see
#: ``machine_config/example/PrintNC-WEBGUI/Machine.ini``) — every
#: value here is a sane default for a bench mill/router, not
#: machine-specific, so it's safe to carry into every generated INI
#: verbatim. The commented ``#INTRO_GRAPHIC``/``#INTRO_TIME`` lines
#: are load-bearing as comments: LinuxCNC's ini parser apparently
#: expects to see those keywords present (even disabled) — the
#: reference file carries them the same way, drop them and keep it
#: working only by accident.
_DISPLAY_DEFAULTS = """\
[DISPLAY]
#DISPLAY = axis
DISPLAY = dummy
EDITOR = gedit
POSITION_OFFSET = RELATIVE
POSITION_FEEDBACK = ACTUAL
ARCDIVISION = 64
GRIDS = 10mm 20mm 50mm 100mm 1in 2in 5in 10in
MAX_FEED_OVERRIDE = 4
MIN_SPINDLE_OVERRIDE = 0.5
MAX_SPINDLE_OVERRIDE = 4
DEFAULT_LINEAR_VELOCITY = 50.00
MIN_LINEAR_VELOCITY = 0
MAX_LINEAR_VELOCITY = 100.00

#INTRO_GRAPHIC = linuxcnc.gif
#INTRO_TIME = 5
PROGRAM_PREFIX = {program_prefix}
INCREMENTS = 5mm 1mm .5mm .1mm .05mm .01mm .005mm

DEFAULT_SPINDLE_SPEED = 6000
"""


def _fmt(value: float) -> str:
    """Format a float without noisy trailing precision (``100.0``, not
    ``100.00000001`` or a bare ``100``)."""
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text if "." in text else f"{text}.0"


def _posix(path) -> str:
    return str(path).replace("\\", "/")


def _coordinates(axes: List[Axis]) -> str:
    """``trivkins coordinates=`` string — one letter per joint, so a
    dual-motor axis repeats its letter (e.g. ``XYYZ``)."""
    return "".join(axis.letter * max(len(axis.joints), 1) for axis in axes)


def _joint_count(axes: List[Axis]) -> int:
    return sum(max(len(axis.joints), 1) for axis in axes)


def _render_axis_section(axis: Axis) -> List[str]:
    lines = [
        f"[AXIS_{axis.letter}]",
        f"MAX_VELOCITY = {_fmt(axis.max_velocity)}",
        f"MAX_ACCELERATION = {_fmt(axis.max_acceleration)}",
        f"MIN_LIMIT = {_fmt(axis.min_limit)}",
        f"MAX_LIMIT = {_fmt(axis.max_limit)}",
    ]
    if axis.letter == "Z":
        # See _OFFSET_AV_RATIO docstring — required for
        # PauseInspectWebguiMapper's Z eoffset wiring to actually move
        # the axis, not just this axis's own envelope.
        lines.append(f"OFFSET_AV_RATIO = {_fmt(_OFFSET_AV_RATIO)}")
    lines.append("")
    return lines


def _render_joint_section(joint, motor_accel_factor: float = 1.0) -> List[str]:
    """``motor_accel_factor``: CoreXY X / Y — STEPGEN_MAXACCEL is the
    Remora step generator's limit, i.e. per belt motor, and a motor sees
    up to the X plus the Y acceleration (A = X + Y)."""
    return [
        f"[JOINT_{joint.joint_number}]",
        f"TYPE = {joint.type}",
        f"HOME = {_fmt(joint.home_position)}",
        f"MIN_LIMIT = {_fmt(joint.min_limit)}",
        f"MAX_LIMIT = {_fmt(joint.max_limit)}",
        f"MAX_VELOCITY = {_fmt(joint.max_velocity)}",
        f"MAX_ACCELERATION = {_fmt(joint.max_acceleration)}",
        f"STEPGEN_MAXACCEL = {_fmt(joint.stepgen_maxaccel * motor_accel_factor)}",
        f"SCALE = {_fmt(joint.scale)}",
        f"FERROR = {_fmt(joint.ferror)}",
        f"MIN_FERROR = {_fmt(joint.min_ferror)}",
        f"HOME_OFFSET = {_fmt(joint.home_offset)}",
        f"HOME_SEARCH_VEL = {_fmt(joint.home_search_vel)}",
        f"HOME_LATCH_VEL = {_fmt(joint.home_latch_vel)}",
        "HOME_USE_INDEX = NO",
        f"HOME_SEQUENCE = {int(joint.home_sequence)}",
        "",
    ]


def _render_heater_section(tool: Dict[str, Any]) -> List[str]:
    """A `[<SECTION>]PID_*` block for one PID-controlled heater.

    `HeaterHalMapper` (`services/halcompiler`) writes `setp
    PID-<id>.KP [<SECTION>]PID_KP` etc. into `machine.hal` for every
    PID heater — those are ini-var *references*, not values, so
    without this section they resolve to nothing and every gain is
    silently 0. `heater_ini_section` is the single shared naming
    function both sides use, so the two can never name the section
    differently. A `watermark` heater has no ini-var references at
    all (`HeaterHalMapper._watermark_loop` uses literals throughout)
    and gets no section here.
    """
    section = heater_ini_section(str(tool["id"]))
    # PID_SPMIN stays 0: `min_temp` is a sensor-fault limit (Klipper), not a
    # set point floor. As SPmin it would lift a target of 0 to min_temp, and
    # the PIDcontroller only switches a heater fully off at a set point of 0.
    max_temp = tool.get("max_temp")
    return [
        f"[{section}]",
        f"PID_PONM = {_DEFAULT_PID_PONM}",
        "PID_DIR = 0",
        f"PID_KP = {_fmt(tool.get('pid_kp') or 0.0)}",
        f"PID_KI = {_fmt(tool.get('pid_ki') or 0.0)}",
        f"PID_KD = {_fmt(tool.get('pid_kd') or 0.0)}",
        "PID_SPMIN = 0.0",
        f"PID_SPMAX = {_fmt(max_temp if max_temp is not None else 0.0)}",
        "PID_CVMIN = 0.0",
        f"PID_CVMAX = {_fmt(_DEFAULT_PID_CVMAX)}",
        "",
    ]


def _ui_home(axes: List[Axis]) -> List[str]:
    """``X = <HOME>`` ... for X, Y, Z: the first joint's ``HOME`` (0 for
    an axis the machine does not have) — read by ``g28.ngc``."""
    by_letter = {a.letter.upper(): a for a in axes}
    lines = []
    for letter in "XYZ":
        axis = by_letter.get(letter)
        home = axis.joints[0].home_position if axis and axis.joints else 0.0
        lines.append(f"{letter} = {_fmt(home)}")
    return lines


def render_ini_template(
    machine_name: str,
    axes: List[Axis],
    tools: List[Dict[str, Any]] | None = None,
    mdi_commands: List[str] | None = None,
    corexy: bool = False,
    homing_override: bool = False,
    remaps: List[str] | None = None,
) -> str:
    """Render a live, loadable ``machine.ini``.

    Args:
        machine_name: Machine name (the source ``.cfg`` file stem) —
            written into ``[EMC] MACHINE`` and used as the ``.cft``
            profile reference.
        axes: The axis/joint list from
            ``AxisBuilder(graph, policy=AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS).build()``
            — one joint per declared stepper, so a multi-motor axis
            (dual-Y gantry) renders every joint.
        tools: The ``hardware.json`` ``tools[]`` list (raw dicts,
            ``build_hardware_json``'s own output — the same shape
            ``HeaterHalMapper`` consumes). Every ``extruder`` /
            ``heated_bed`` tool with ``control: "pid"`` (the default)
            gets a matching ``[<SECTION>]PID_*`` block; ``None`` or a
            tool-less profile renders none, same as before this
            parameter existed.
        mdi_commands: ``[HALUI] MDI_COMMAND`` lines, in
            ``halui.mdi-command-NN`` order (an ``[input_pin]``'s edges,
            ``IoPinHalMapper.mdi_commands``); their subroutines live in
            the config's ``subroutines/`` folder.
        corexy: CoreXY kinematics instead of ``trivkins``.
        homing_override: The machine homes with a ``[homing_override]``
            routine — ``[TRAJ] NO_FORCE_HOMING = 1`` so the routine's
            moves run before every joint is homed.
        remaps: ``[RS274NGC] REMAP=`` lines (Marlin heater / fan codes,
            ``marlin_mcodes``); their subroutines and helper M-codes
            are the shared files in ``machine_config/m_codes/``.
    """
    tools = tools or []
    mdi_commands = mdi_commands or []
    joint_count = _joint_count(axes)
    coordinates = _coordinates(axes) or "X"

    # Trajectory-level velocity is bounded by the slowest axis — a
    # machine can't move faster along a combined path than its
    # slowest contributing axis allows.
    axis_velocities = [a.max_velocity for a in axes if a.max_velocity > 0]
    traj_max_velocity = min(axis_velocities) if axis_velocities else 40.0
    traj_default_velocity = min(traj_max_velocity, max(traj_max_velocity * 0.1, 1.0))

    lines: List[str] = [
        "# machine.ini - generated by the LinuxCNC_UI machine templates",
        f"# Machine: {machine_name}",
        "#",
        "# This INI is meant to load and run in LinuxCNC (trivkins), not to",
        "# be a fully tuned, ready-to-cut machine. HAL wiring in machine.hal",
        "# still needs the operator's own pin assignments.",
        "",
        "[EMC]",
        f"MACHINE = {machine_name}",
        "DEBUG = 0",
        "VERSION = 1.1",
        "",
        _DISPLAY_DEFAULTS.format(program_prefix=_posix(paths.NC_FILES_DIR) + "/").rstrip("\n"),
        "",
        "[KINS]",
        f"JOINTS = {joint_count}",
        f"KINEMATICS = trivkins coordinates={coordinates}",
        "",
        "[TASK]",
        "TASK = milltask",
        "CYCLE_TIME = 0.010",
        "",
        "[RS274NGC]",
        "PARAMETER_FILE = linuxcnc.var",
        f"USER_M_PATH = {_posix(paths.M_CODES_DIR)}",
        # ``o<name> call`` (macros / probing cycles) looks subroutines up
        # here; m_codes/ holds the shared Marlin remaps and g28.ngc.
        f"SUBROUTINE_PATH = {_posix(paths.MACROS_DIR)}:{_posix(paths.M_CODES_DIR)}"
        + (f":{SUBROUTINES_DIR}" if mdi_commands else ""),
        *(remaps or []),
        "",
        # Home positions in machine coordinates, for m_codes/g28.ngc (a
        # slicer's G28 inside a program: a move there, not a home).
        "[UI_HOME]",
        *_ui_home(axes),
        "",
        "[EMCMOT]",
        "EMCMOT = motmod",
        "COMM_TIMEOUT = 30.0",
        "BASE_PERIOD = 100000",
        "SERVO_PERIOD = 1000000",
        "",
        "[HAL]",
        "HALFILE = machine.hal",
        # The operator's own HAL, never regenerated: after machine.hal
        # (its signals exist), before custom.hal (webgui_connections.hal
        # may read a pin a component loaded here creates).
        "HALFILE = user.hal",
        "HALFILE = custom.hal",
        "POSTGUI_HALFILE = postgui_call_list.hal",
        "HALUI = halui",
        "",
        *(["[HALUI]", *mdi_commands, ""] if mdi_commands else []),
        "[TRAJ]",
        f"COORDINATES = {coordinates}",
        "LINEAR_UNITS = mm",
        "ANGULAR_UNITS = degree",
        f"DEFAULT_LINEAR_VELOCITY = {_fmt(traj_default_velocity)}",
        f"MAX_LINEAR_VELOCITY = {_fmt(traj_max_velocity)}",
        # [homing_override]: the routine moves before every joint is
        # homed (e.g. lift Z clear), which LinuxCNC refuses otherwise.
        # The UI still refuses to start a program until all are homed.
        *(["NO_FORCE_HOMING = 1"] if homing_override else []),
        "",
        "[EMCIO]",
        "EMCIO = io",
        "CYCLE_TIME = 0.100",
        "TOOL_TABLE = tool.tbl",
        "",
    ]

    for axis in axes:
        lines.extend(_render_axis_section(axis))
        factor = 2.0 if corexy and axis.letter in ("X", "Y") else 1.0
        for joint in axis.joints:
            lines.extend(_render_joint_section(joint, factor))

    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") not in ("extruder", "heated_bed"):
            continue
        if (tool.get("control") or "pid") != "pid":
            continue
        lines.extend(_render_heater_section(tool))

    return "\n".join(lines).rstrip("\n") + "\n"


__all__ = ["render_ini_template"]
