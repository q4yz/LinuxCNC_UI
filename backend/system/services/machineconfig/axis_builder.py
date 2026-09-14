"""Build LinuxCNC :class:`Axis` / :class:`Joint` objects from a parsed Klipper graph.

The builder is the bridge between the input-side
:class:`~..models.klipper_models.MachineConfigGraph` and the
output-side :class:`~..models.linuxcnc_models.Axis` /
:class:`~..models.linuxcnc_models.Joint` model. It enforces no
strict 1:1 axis-to-joint mapping; a single Klipper axis letter may
end up with multiple joints (dual-motor Y) or vice versa if a
future Klipper profile ever needs that.

Why a builder rather than direct conversion?

* The mapping policy lives in *one* place. The renderer never has
  to know whether ``stepper_y`` + ``stepper_y1`` is one axis or two.
* Adding a future Klipper construct (rotational axes, a second
  Z stepper, kinematic switches) is a builder change, not a
  renderer change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from models.machineconfig import (
    AXIS_ORDER,
    Axis,
    Joint,
    MachineConfigGraph,
    Stepper,
)

logger = logging.getLogger("backend.services.machineconfig.axis_builder")

# Standard 1.8° stepper motors have 200 full steps per revolution —
# the fallback when the profile doesn't say. A 0.9° motor is 400, and
# a profile that declares ``full_steps_per_rotation`` overrides this.
# ``rotation_distance`` from Klipper (mm / full revolution) becomes
# LinuxCNC ``SCALE`` (steps / unit) via:
#
#     SCALE = (microsteps * full_steps_per_rotation) / rotation_distance
FULL_STEPS_PER_REVOLUTION = 200

#: ``HOME_SEQUENCE`` phase per axis letter — LinuxCNC homes phases in
#: increasing order (by absolute value), joints sharing one phase move
#: together. Verified against a real, working PrintNC machine.ini/
#: machine.hal pair: Z homes alone first (phase 0, clears the tool
#: from the work), Y homes second (phase 1, both gantry joints
#: simultaneously — see :meth:`_negate_gantry_home_sequences` for the
#: negative sign), X homes last (phase 2, alone — the same reference
#: machine has X and Z sharing one physical switch, and homes them in
#: separate phases with no other special handling: no
#: ``HOME_IS_SHARED``, just each axis fully retracting off the switch
#: before the next phase starts). Deliberately just these three fixed
#: phases, not one per axis — a machine that needs a different order
#: does it with a homing macro instead; the compiler only owns this
#: one verified, common case. An axis letter not listed here (e.g. the
#: extruder's synthetic "A") keeps the pre-existing default of 0.
_HOME_SEQUENCE_BY_AXIS: dict[str, int] = {"Z": 0, "Y": 1, "X": 2}


def _get_float(stepper: Stepper, name: str, default: float) -> float:
    """Read an optional float field off a :class:`Stepper`.

    The Klipper schema today doesn't accept ``position_min`` /
    ``homing_speed`` as stepper-level keywords, so they aren't on
    every :class:`Stepper` instance. ``getattr`` with a default
    keeps the builder forward-compatible when those fields land.
    """

    raw = getattr(stepper, name, None)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------- #
# Scale helper                                                           #
# --------------------------------------------------------------------- #


def stepgen_scale(stepper: Stepper) -> float:
    """LinuxCNC ``SCALE`` (steps / unit) from a Klipper stepper.

    Returns 0.0 when the inputs are missing — the caller is
    expected to surface that as a validation error before reaching
    the renderer.
    """
    if stepper.rotation_distance in (None, 0) or stepper.microsteps is None:
        return 0.0
    full_steps = getattr(stepper, "full_steps_per_rotation", None) or FULL_STEPS_PER_REVOLUTION
    return (stepper.microsteps * full_steps) / stepper.rotation_distance


# --------------------------------------------------------------------- #
# Axis mapping policy                                                    #
# --------------------------------------------------------------------- #


@dataclass(slots=True)
class AxisMappingPolicy:
    """How multiple Klipper steppers on one axis map to joints.

    The default :data:`MERGE_INTO_SINGLE_JOINT` policy collapses
    ``stepper_y`` + ``stepper_y1`` into one joint because the
    current LinuxCNC HAL template has no per-joint dual-motor
    wiring. The other strategies are forward-compatible — the
    renderer emits one ``[JOINT_N]`` per joint regardless.
    """

    MERGE_INTO_SINGLE_JOINT = "merge"
    SPLIT_INTO_MULTIPLE_JOINTS = "split"
    FIRST_WINS = "first"


class AxisBuilder:
    """Build the LinuxCNC axis / joint list from a parsed graph.

    Parameters
    ----------
    graph:
        Parsed Klipper profile.
    policy:
        How to handle multiple steppers on one axis. Default is
        :data:`AxisMappingPolicy.MERGE_INTO_SINGLE_JOINT`.
    joint_number_allocator:
        Callable that returns the next joint number; defaults to
        a sequential counter starting at 0.
    """

    def __init__(
        self,
        graph: MachineConfigGraph,
        policy: str = AxisMappingPolicy.MERGE_INTO_SINGLE_JOINT,
        joint_number_allocator: Callable[[], int] | None = None,
    ) -> None:
        self.graph = graph
        self.policy = policy
        self._next_joint = joint_number_allocator or self._sequential_allocator()
        # Cache for axis-by-letter so ``build_axis`` is idempotent
        # within one ``build`` call.
        self._axes: dict[str, Axis] = {}

    def _sequential_allocator(self) -> Callable[[], int]:
        counter = {"n": 0}

        def alloc() -> int:
            n = counter["n"]
            counter["n"] += 1
            return n

        return alloc

    # ----- Public API ----------------------------------------------- #

    def build(self) -> list[Axis]:
        """Return the axes in canonical LinuxCNC order (X, Y, Z, ...)."""
        from models.machineconfig import Extruder

        for stepper in self.graph.steppers.values():
            self._add_stepper(stepper)

        # The extruder is its own axis (``A``) even though it lives
        # under ``graph.heaters`` rather than ``graph.steppers``. We
        # synthesise an axis per :class:`Extruder` so the config_txt
        # generator can emit a Joint-N stepgen for the extruder.
        for heater in self.graph.heaters.values():
            if isinstance(heater, Extruder):
                self._axes.setdefault("A", Axis(
                    letter="A",
                    joints=[],
                ))
                # Must continue the SAME global sequence every other
                # joint uses (`self._next_joint()`), not restart from
                # the A axis's own local joint count. A machine with
                # X/Y/Z already claiming 0/1/2 previously got an
                # extruder joint ALSO numbered 0 — a real collision:
                # two different joints both wired as `[JOINT_0]` /
                # `remora.joint.0.*`.
                joint = self._make_extruder_joint(heater, self._next_joint())
                self._axes["A"].joints.append(joint)

        ordered: list[Axis] = []
        for letter in AXIS_ORDER:
            if letter in self._axes:
                ordered.append(self._axes[letter])
        # Any unmapped letters (future A/B/C) trail in alphabetical
        # order so the renderer never silently drops them.
        for letter, axis in self._axes.items():
            if letter not in AXIS_ORDER and axis not in ordered:
                ordered.append(axis)

        self._negate_gantry_home_sequences(ordered)
        return ordered

    @staticmethod
    def _negate_gantry_home_sequences(axes: list[Axis]) -> None:
        """A multi-joint (gantry) axis's ``HOME_SEQUENCE`` must be
        negative on every one of its joints — the sign, not the
        number, is what tells LinuxCNC's homing state machine "these
        joints home together and latch independently to square the
        gantry" rather than just "these happen to share a phase".
        A single-joint axis is never touched (stays positive/0)."""
        for axis in axes:
            if len(axis.joints) <= 1:
                continue
            for joint in axis.joints:
                joint.home_sequence = -abs(joint.home_sequence)

    # ----- Internals ------------------------------------------------ #

    def _add_stepper(self, stepper: Stepper) -> None:
        letter = stepper.axis.upper()
        axis = self._axes.get(letter) or self._new_axis(letter, stepper)

        if self.policy == AxisMappingPolicy.MERGE_INTO_SINGLE_JOINT:
            self._merge_into_axis(axis, stepper)
        elif self.policy == AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS:
            self._append_joint(axis, stepper)
        elif self.policy == AxisMappingPolicy.FIRST_WINS:
            if not axis.joints:
                self._append_joint(axis, stepper)
        else:
            raise ValueError(f"Unknown axis mapping policy: {self.policy}")

    def _new_axis(self, letter: str, stepper: Stepper) -> Axis:
        axis = Axis(
            letter=letter,
            max_velocity=self._printer_velocity() if letter != "Z" else 5.0,
            max_acceleration=self._printer_accel() if letter != "Z" else 200.0,
            min_limit=_get_float(stepper, "position_min", 0.0),
            max_limit=_get_float(stepper, "position_max", 0.0),
        )
        if letter == "Z":
            axis.offset_av_ratio = 0.2
        self._axes[letter] = axis
        return axis

    def _merge_into_axis(self, axis: Axis, stepper: Stepper) -> None:
        """Replace any existing joint on ``axis`` with this stepper.

        The merge policy keeps ``stepper_y`` and ``stepper_y1``
        indistinguishable downstream — the renderer sees one joint.
        """
        joint = self._make_joint(stepper, axis.letter, joint_number=self._next_joint())
        axis.joints = [joint]
        self._apply_axis_envelope_from_joint(axis, joint)

    def _append_joint(self, axis: Axis, stepper: Stepper) -> None:
        # A second (and later) stepper on a SPLIT axis is a gantry
        # motor sharing the first joint's rail — Klipper convention is
        # that only the primary stepper (``stepper_y``) declares
        # ``position_min``/``position_max``/``position_endstop``/
        # ``homing_speed``; ``stepper_y1`` etc. only carry pin/motor
        # fields. Without a fallback, ``_make_joint`` would silently
        # default those to 0 for every joint after the first.
        joint = self._make_joint(
            stepper, axis.letter, joint_number=self._next_joint(), fallback=axis.primary_joint
        )
        axis.joints.append(joint)
        if len(axis.joints) == 1:
            self._apply_axis_envelope_from_joint(axis, joint)

    def _make_joint(
        self, stepper: Stepper, letter: str, joint_number: int, fallback: Joint | None = None
    ) -> Joint:
        fallback_min = fallback.min_limit if fallback else 0.0
        fallback_max = fallback.max_limit if fallback else 0.0
        fallback_home = fallback.home_position if fallback else 0.0
        fallback_search_vel = fallback.home_search_vel if fallback else 0.0

        homing_speed = _get_float(stepper, "homing_speed", fallback_search_vel)
        position_endstop = (
            float(stepper.position_endstop)
            if stepper.position_endstop is not None
            else fallback_home
        )
        return Joint(
            joint_number=joint_number,
            axis_letter=letter,
            min_limit=_get_float(stepper, "position_min", fallback_min),
            max_limit=_get_float(stepper, "position_max", fallback_max),
            max_velocity=self._stepper_velocity(stepper) or self._printer_velocity(),
            max_acceleration=self._stepper_accel(stepper) or self._printer_accel(),
            stepgen_maxaccel=(self._stepper_accel(stepper) or self._printer_accel()) * 1.1,
            home_position=position_endstop,
            home_offset=position_endstop,
            home_search_vel=homing_speed or 10.0,
            home_latch_vel=homing_speed or 10.0,
            home_sequence=_HOME_SEQUENCE_BY_AXIS.get(letter, 0),
            scale=stepgen_scale(stepper),
            ferror=2.0 if letter != "Y" else 9.0,
            min_ferror=1.0 if letter != "Y" else 5.0,
            step_pin=stepper.step_pin,
            dir_pin=stepper.dir_pin,
            enable_pin=stepper.enable_pin,
        )

    def _apply_axis_envelope_from_joint(self, axis: Axis, joint: Joint) -> None:
        axis.max_velocity = joint.max_velocity
        axis.max_acceleration = joint.max_acceleration
        axis.min_limit = joint.min_limit
        axis.max_limit = joint.max_limit

    def _make_extruder_joint(self, extruder, joint_number: int) -> Joint:
        """Build a synthetic :class:`Joint` for an :class:`Extruder`.

        The Extruder dataclass carries the stepper fields
        (``step_pin`` / ``dir_pin`` / ``enable_pin`` /
        ``microsteps`` / ``rotation_distance``); we re-use
        :meth:`_make_joint` so the velocity / acceleration defaults
        match the Cartesian joints.
        """
        # The extruder has no ``axis`` attribute on the dataclass;
        # create a stub :class:`Stepper` so the existing helper can
        # compute scale + velocity without a full rewrite.
        from models.machineconfig import Stepper

        stub = Stepper(
            axis="A",
            step_pin=extruder.step_pin,
            dir_pin=extruder.dir_pin,
            enable_pin=extruder.enable_pin,
            microsteps=extruder.microsteps,
            rotation_distance=extruder.rotation_distance,
        )
        return self._make_joint(stub, "A", joint_number=joint_number)

    # ----- Velocity helpers ---------------------------------------- #

    def _printer_velocity(self) -> float:
        if self.graph.printer and self.graph.printer.max_velocity is not None:
            return float(self.graph.printer.max_velocity)
        return 250.0

    def _printer_accel(self) -> float:
        if self.graph.printer and self.graph.printer.max_accel is not None:
            return float(self.graph.printer.max_accel)
        return 750.0

    def _stepper_velocity(self, stepper: Stepper) -> float:
        raw = getattr(stepper, "max_velocity", None)
        return float(raw) if raw is not None else 0.0

    def _stepper_accel(self, stepper: Stepper) -> float:
        raw = getattr(stepper, "max_accel", None)
        return float(raw) if raw is not None else 0.0


__all__ = [
    "AxisBuilder",
    "AxisMappingPolicy",
    "FULL_STEPS_PER_REVOLUTION",
    "stepgen_scale",
]