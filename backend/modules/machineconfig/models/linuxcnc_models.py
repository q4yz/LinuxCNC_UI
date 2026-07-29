"""LinuxCNC-side data model.

The LinuxCNC vocabulary is deliberately richer than Klipper's:

* A Klipper ``[printer]`` block maps to a single LinuxCNC ``[TRAJ]``
  section plus per-axis ``[AXIS_*]`` blocks.
* A Klipper ``[stepper_x]`` block maps to a single
  :class:`Joint`. Multiple Klipper steppers on one axis (e.g.
  ``[stepper_y]`` + ``[stepper_y1]``) map to **multiple joints**
  inside **one** :class:`Axis` — the axis owns the list, not the
  other way around.

This file is the only place the one-to-many axis→joint relationship
is modelled. Everything else (INI renderer, future HAL renderer,
validators) consumes :class:`Axis` / :class:`Joint` instances and
never sees the raw Klipper ``stepper_*`` sections directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


JointType = Literal["LINEAR", "ANGULAR"]


@dataclass(slots=True)
class Joint:
    """One LinuxCNC ``[JOINT_N]`` block — a physical motor.

    A joint always belongs to exactly one :class:`Axis` and is the
    granularity at which LinuxCNC emits homing, scaling, and stepgen
    configuration. Multiple joints on the same axis are how
    multi-motor configurations (e.g. dual-Y gantries) are modelled.
    """

    joint_number: int
    axis_letter: str
    type: JointType = "LINEAR"

    # Travel limits. LinuxCNC prefers these in MIN_LIMIT / MAX_LIMIT
    # form; Klipper ``position_min`` / ``position_max`` map 1:1.
    min_limit: float = 0.0
    max_limit: float = 0.0

    # Motion envelope.
    max_velocity: float = 0.0
    max_acceleration: float = 0.0
    stepgen_maxaccel: float = 0.0

    # Homing.
    home_position: float = 0.0
    home_offset: float = 0.0
    home_search_vel: float = 0.0
    home_latch_vel: float = 0.0
    home_sequence: int = 0

    # Scale (steps / unit). Built from Klipper's
    # ``microsteps * 200 / rotation_distance`` by
    # :meth:`AxisBuilder.build_from_graph`.
    scale: float = 0.0

    # Following error — per-joint because LinuxCNC reads FERROR
    # from the JOINT block, not the AXIS block.
    ferror: float = 2.0
    min_ferror: float = 1.0

    # Hardware pins (from the Klipper ``step_pin`` / ``dir_pin`` /
    # ``enable_pin`` keywords). These are documentation-only in the
    # HAL file — the actual pin mapping lives in the Remora firmware
    # config (``boardConfig.h``).
    step_pin: str | None = None
    dir_pin: str | None = None
    enable_pin: str | None = None

    @property
    def section_name(self) -> str:
        """The INI section name for this joint (``JOINT_0`` etc.)."""

        return f"JOINT_{self.joint_number}"


@dataclass(slots=True)
class Axis:
    """One LinuxCNC ``[AXIS_X]`` block — a logical axis letter.

    An axis owns the list of joints that drive it. The 1:1 case
    (``stepper_x`` only) yields a single-element ``joints`` list.
    Dual-motor setups (``stepper_y`` + ``stepper_y1``) yield a
    two-element list.
    """

    letter: str
    joints: list[Joint] = field(default_factory=list)

    # Axis-level envelope. LinuxCNC reads both AXIS_* and JOINT_*
    # for these, so we duplicate the values on both sides.
    max_velocity: float = 0.0
    max_acceleration: float = 0.0
    min_limit: float = 0.0
    max_limit: float = 0.0

    # Z-specific offset/AV ratio, None on X/Y.
    offset_av_ratio: float | None = None

    @property
    def section_name(self) -> str:
        """The INI section name for this axis (``AXIS_X`` etc.)."""

        return f"AXIS_{self.letter}"

    @property
    def primary_joint(self) -> Joint | None:
        """The first joint, used for the JOINT block paired with AXIS.

        Future multi-motor renderers may emit additional JOINT blocks
        for the secondary joints.
        """

        return self.joints[0] if self.joints else None


# Canonical axis ordering — LinuxCNC expects X, Y, Z, then any
# rotational axes. Used by the renderer so the output is stable.
AXIS_ORDER: tuple[str, ...] = ("X", "Y", "Z", "A", "B", "C")


@dataclass(slots=True)
class IniConfig:
    """Top-level LinuxCNC INI representation.

    ``printer`` is the Klipper-side :class:`MachineConfigGraph` kept
    for renderer convenience; ``axes`` is the ordered list of
    LinuxCNC :class:`Axis` objects to emit, pre-resolved by
    :class:`AxisBuilder`.
    """

    printer: object | None = None  # Klipper ``MachineConfigGraph``
    axes: list[Axis] = field(default_factory=list)
    joints_count: int = 0
    coordinates: str = "X Y Z"
    kinematics_name: str = "trivkins"


__all__ = [
    "AXIS_ORDER",
    "Axis",
    "IniConfig",
    "Joint",
    "JointType",
]