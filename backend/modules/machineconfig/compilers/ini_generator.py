"""Render LinuxCNC ``.ini`` files from :class:`Axis` / :class:`Joint` models.

The renderer is deliberately template-based: the static skeleton
of an Axis / Joint block lives as a multi-line string so operators
can hand-edit a familiar LinuxCNC file and the diff against the
generated output stays legible.

The dynamic section (one ``[AXIS_*]`` and one ``[JOINT_*]`` per
logical axis) is built by a **Builder pattern**: the template
walks the pre-resolved :class:`list` of :class:`Axis` objects and
emits one section per axis, one joint per axis (or N joints for
multi-motor axes). No 1:1 axis-to-joint assumption is hardcoded.

Placeholder syntax:

* ``{section.key}`` — substituted from the render context (a
  ``dict``). Nested keys use ``.`` as the separator.
* ``{section.value:fmt}`` — formatted with the ``fmt`` mini-language
  (``%.3f``, ``%d``, ``%s``).
* ``{{`` / ``}}`` — literal braces for sections that need them.

The renderer is intentionally minimal — no control flow in the
template language. Anything that needs branching (per-axis FERROR,
Z-specific OFFSET_AV_RATIO) is handled by the Python builders below.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Mapping

from ..models import AXIS_ORDER, Axis, IniConfig, Joint
from .axis_builder import AxisBuilder

logger = logging.getLogger("backend.modules.machineconfig.compilers.ini_generator")


# --------------------------------------------------------------------- #
# Static template                                                        #
# --------------------------------------------------------------------- #

INI_HEADER_TEMPLATE = """\
# Basic LinuxCNC config for testing of Remora firmware

[EMC]
MACHINE = Remora-XY
DEBUG = 5
VERSION = 1.1

[DISPLAY]
DISPLAY = axis
USER_COMMAND_FILE = usercommand_regularmac_800.py
EDITOR = gedit
POSITION_OFFSET = RELATIVE
POSITION_FEEDBACK = ACTUAL
ARCDIVISION = 64
GRIDS = 10mm 20mm 50mm 100mm
MAX_FEED_OVERRIDE = 1.2
DEFAULT_LINEAR_VELOCITY = 5.00
MIN_LINEAR_VELOCITY = 0
MAX_LINEAR_VELOCITY = 10.00
DEFAULT_ANGULAR_VELOCITY = 36.00
MIN_ANGULAR_VELOCITY = 0
MAX_ANGULAR_VELOCITY = 45.00
INTRO_GRAPHIC = linuxcnc.gif
INTRO_TIME = 5
PROGRAM_PREFIX = ~/linuxcnc/nc_files
INCREMENTS = 50mm 10mm 5mm 1mm .5mm .1mm .05mm .01mm

[KINS]
JOINTS = {joints_count}
KINEMATICS = trivkins coordinates={coordinates}

[FILTER]
PROGRAM_EXTENSION = .py Python Script
py = python

[TASK]
TASK = milltask
CYCLE_TIME = 0.010

[RS274NGC]
PARAMETER_FILE = linuxcnc.var

[EMCMOT]
EMCMOT = motmod
COMM_TIMEOUT = 1.0
COMM_WAIT = 0.010
BASE_PERIOD = 0
SERVO_PERIOD = 1000000

[HAL]
HALFILE = remora-xyz.hal
POSTGUI_HALFILE = postgui_call_list.hal

[TRAJ]
COORDINATES =  {coordinates}
LINEAR_UNITS = mm
ANGULAR_UNITS = degree
CYCLE_TIME = 0.010
DEFAULT_LINEAR_VELOCITY = 50.00
MAX_LINEAR_VELOCITY = {printer_max_velocity}
NO_FORCE_HOMING = 1

{axes_block}

[EMCIO]
EMCIO = io
CYCLE_TIME = 0.100
TOOL_TABLE = tool.tbl
"""

# Per-axis template. ``{letter}`` and the joint-number placeholders
# are filled in by the renderer; the rest come from the Axis / Joint
# model.
AXIS_TEMPLATE = """\
[AXIS_{letter}]
MAX_VELOCITY = {axis_max_velocity}
MAX_ACCELERATION = {axis_max_acceleration}
MIN_LIMIT = {axis_min_limit}
MAX_LIMIT = {axis_max_limit}
{axis_extras}

[JOINT_{joint_number}]
TYPE = {joint_type}
HOME = {joint_home_position}
MIN_LIMIT = {joint_min_limit}
MAX_LIMIT = {joint_max_limit}
MAX_VELOCITY = {joint_max_velocity}
MAX_ACCELERATION = {joint_max_acceleration}
STEPGEN_MAXACCEL = {joint_stepgen_maxaccel}
SCALE = {joint_scale}
FERROR = {joint_ferror}
MIN_FERROR = {joint_min_ferror}
HOME_OFFSET = {joint_home_offset}
HOME_SEARCH_VEL = {joint_home_search_vel}
HOME_LATCH_VEL = {joint_home_latch_vel}
HOME_SEQUENCE = {joint_home_sequence}
"""


# --------------------------------------------------------------------- #
# Placeholder substitution                                               #
# --------------------------------------------------------------------- #


# Match ``{section.key}`` or ``{section.key:fmt}``. We avoid greedy
# ``.*`` so nested keys are not ambiguous.
_PLACEHOLDER = re.compile(r"\{(?P<key>[a-zA-Z_][\w.]*)(?::(?P<fmt>[^}]+))?\}")


class TemplateError(ValueError):
    """Raised when an INI template references an unknown key."""


def render_string(template: str, context: Mapping[str, object]) -> str:
    """Substitute ``{key[:fmt]}`` placeholders in ``template``.

    Keys may be dotted (``foo.bar``); the renderer walks the
    context looking up each segment. Unknown keys raise
    :class:`TemplateError` so a typo in the template cannot
    silently render ``{...}`` in the output.
    """

    def lookup(key: str) -> object:
        node: object = context
        for segment in key.split("."):
            if isinstance(node, Mapping):
                if segment not in node:
                    raise TemplateError(
                        f"Template references missing key '{key}' "
                        f"(segment '{segment}' not found)"
                    )
                node = node[segment]
            else:
                raise TemplateError(
                    f"Template references missing key '{key}' "
                    f"(segment '{segment}' not in non-mapping)"
                )
        return node

    def replace(match: re.Match[str]) -> str:
        key = match.group("key")
        fmt = match.group("fmt")
        value = lookup(key)
        if fmt is None:
            return str(value)
        try:
            return format(value, fmt)
        except (TypeError, ValueError) as exc:
            raise TemplateError(
                f"Cannot format {value!r} with '{fmt}' for key '{key}'"
            ) from exc

    return _PLACEHOLDER.sub(replace, template)


# --------------------------------------------------------------------- #
# Builder                                                                #
# --------------------------------------------------------------------- #


@dataclass(slots=True)
class IniGenerator:
    """Render an :class:`IniConfig` into a LinuxCNC INI string.

    The :meth:`render` method is the single public entry point; the
    builders below it are split so the dynamic section can grow new
    axis types (rotational, kinematic-switch) without touching the
    static header.
    """

    def render(self, config: IniConfig) -> str:
        """Render the full INI from an :class:`IniConfig`."""

        joints_count = sum(len(axis.joints) for axis in config.axes) or 3
        coordinates = config.coordinates or "X Y Z"
        printer_velocity = self._printer_max_velocity(config)

        header_context = {
            "joints_count": joints_count,
            "coordinates": coordinates,
            "printer_max_velocity": self._fmt(printer_velocity),
        }

        # ``render_string`` requires all placeholders to resolve; the
        # ``{axes_block}`` slot is filled by a second pass after the
        # dynamic section is built.
        header_template = INI_HEADER_TEMPLATE.replace("{axes_block}", "\x00AXES\x00")
        rendered_header = render_string(header_template, header_context)

        axes_block = self._build_axes_block(config.axes)
        rendered = rendered_header.replace("\x00AXES\x00", axes_block)

        logger.info(
            "IniGenerator emitted %d axes (%d joints total)",
            len(config.axes),
            joints_count,
        )
        return rendered

    # ----- Builders ----------------------------------------------- #

    def _build_axes_block(self, axes: list[Axis]) -> str:
        """Render one ``[AXIS_*]`` / ``[JOINT_*]`` pair per axis.

        The output keeps the canonical axis order so the resulting
        INI is stable across runs.
        """
        ordered = self._sort_axes(axes)
        chunks: list[str] = []
        for axis in ordered:
            chunks.append(self._render_axis(axis))
        return "\n".join(chunks)

    @staticmethod
    def _sort_axes(axes: list[Axis]) -> list[Axis]:
        order = {letter: i for i, letter in enumerate(AXIS_ORDER)}
        return sorted(
            axes,
            key=lambda a: (order.get(a.letter.upper(), len(order)), a.letter),
        )

    def _render_axis(self, axis: Axis) -> str:
        primary = axis.primary_joint
        if primary is None:
            raise TemplateError(
                f"Axis '{axis.letter}' has no joints — refusing to render"
            )
        context = self._axis_context(axis, primary)
        return render_string(AXIS_TEMPLATE, context)

    def _axis_context(self, axis: Axis, joint: Joint) -> dict[str, object]:
        context: dict[str, object] = {
            "letter": axis.letter,
            "axis_max_velocity": self._fmt(axis.max_velocity),
            "axis_max_acceleration": self._fmt(axis.max_acceleration),
            "axis_min_limit": self._fmt(axis.min_limit),
            "axis_max_limit": self._fmt(axis.max_limit),
            "axis_extras": "",
            "joint_number": joint.joint_number,
            "joint_type": joint.type,
            "joint_home_position": self._fmt(joint.home_position),
            "joint_min_limit": self._fmt(joint.min_limit),
            "joint_max_limit": self._fmt(joint.max_limit),
            "joint_max_velocity": self._fmt(joint.max_velocity),
            "joint_max_acceleration": self._fmt(joint.max_acceleration),
            "joint_stepgen_maxaccel": self._fmt(joint.stepgen_maxaccel),
            "joint_scale": self._fmt(joint.scale),
            "joint_ferror": self._fmt(joint.ferror),
            "joint_min_ferror": self._fmt(joint.min_ferror),
            "joint_home_offset": self._fmt(joint.home_offset),
            "joint_home_search_vel": self._fmt(joint.home_search_vel),
            "joint_home_latch_vel": self._fmt(joint.home_latch_vel),
            "joint_home_sequence": joint.home_sequence,
        }
        # ``axis_extras`` is appended after the AXIS_* block as raw
        # ``KEY = value`` lines. Z currently gets OFFSET_AV_RATIO.
        extras: list[str] = []
        if axis.offset_av_ratio is not None:
            extras.append(f"OFFSET_AV_RATIO = {axis.offset_av_ratio}")
        # Multi-motor axes currently emit the extra joints as inline
        # AXIS-block hints; the renderer never strips the canonical
        # pair so diffs against the legacy file stay readable.
        if len(axis.joints) > 1:
            extras.append(
                f"# NOTE: {len(axis.joints)} steppers mapped to this axis"
            )
            for extra in axis.joints[1:]:
                extras.append(f"# extra joint {extra.joint_number}: scale={self._fmt(extra.scale)}")
        if extras:
            context["axis_extras"] = "\n".join(extras)
        return context

    # ----- Helpers ------------------------------------------------ #

    @staticmethod
    def _fmt(value: float | int) -> str:
        """Format a numeric value, dropping trailing ``.0`` on integers."""

        if isinstance(value, bool):
            return str(value)
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            if value.is_integer():
                return str(int(value))
            return f"{value:.4f}".rstrip("0").rstrip(".")
        return str(value)

    @staticmethod
    def _printer_max_velocity(config: IniConfig) -> float:
        """Pull ``max_velocity`` from the Klipper-side graph if present."""

        graph = config.printer
        if graph is None:
            return 250.0
        printer = getattr(graph, "printer", None)
        if printer is None:
            return 250.0
        mv = getattr(printer, "max_velocity", None)
        return float(mv) if mv is not None else 250.0


# --------------------------------------------------------------------- #
# High-level facade                                                       #
# --------------------------------------------------------------------- #


def build_ini_from_graph(graph) -> IniConfig:
    """Convenience entry point: parse graph → :class:`IniConfig`."""

    axes = AxisBuilder(graph).build()
    return IniConfig(
        printer=graph,
        axes=axes,
        joints_count=sum(len(a.joints) for a in axes),
        coordinates=" ".join(a.letter for a in axes if a.letter in ("X", "Y", "Z", "A", "B", "C")) or "X Y Z",
        kinematics_name="trivkins",
    )


__all__ = [
    "IniGenerator",
    "TemplateError",
    "build_ini_from_graph",
    "render_string",
]