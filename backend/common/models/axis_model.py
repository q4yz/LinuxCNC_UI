from typing import List, Optional

from pydantic import BaseModel, Field


class AxisStateResponse(BaseModel):
    """JSON response model for axis configuration.

    Identified by a string ``id`` (the canonical LinuxCNC letter —
    ``x``, ``y``, ``z``, ``a``, ...) and lists every driving joint as
    ``joint_numbers``. Joints are the physical motors and remain
    keyed by integer ``joint_number`` (Remora stepgen channel
    ``remora.joint.{N}.*``); the axis is the logical coordinate
    frame that owns one or more joints.
    """
    id: str = Field(
        ...,
        description=(
            "Canonical LinuxCNC axis letter — 'x', 'y', 'z', 'a', ... "
            "Identifies the logical axis that owns one or more joints."
        ),
    )
    joint_numbers: Optional[List[int]] = Field(
        None,
        description=(
            "All joint_numbers driving this axis. For a single-motor "
            "axis the list has one element. Multi-motor axes (e.g. "
            "dual-motor Y) list every joint."
        ),
    )
    # Static-tier fields: ``None`` on the base tier (the mapper masks
    # them), which used to fail validation and 500 ``?mode=base``.
    min_limit: Optional[float] = Field(None, description="Minimum soft limit for the axis")
    max_limit: Optional[float] = Field(None, description="Maximum soft limit for the axis")
    max_velocity: Optional[float] = Field(
        None,
        description="Axis velocity limit in mm/s ([AXIS_*] MAX_VELOCITY); null when the machine config has none.",
    )
    max_acceleration: Optional[float] = Field(
        None,
        description="Axis acceleration limit in mm/s² ([AXIS_*] MAX_ACCELERATION); null when the machine config has none.",
    )


class SpeedOverrideResponse(BaseModel):
    """Live speed override state (base-thread snapshot, 1 Hz).

    Read back from LinuxCNC so the UI's override sliders show what the
    controller actually applies, not what the UI last asked for.
    """
    feed_override: Optional[float] = Field(
        None,
        description="Feed override as a fraction (1.0 = 100 %) — LinuxCNC's stat.feedrate. Null when unknown.",
    )
    max_velocity: Optional[float] = Field(
        None,
        description="Absolute trajectory speed cap in mm/s — LinuxCNC's stat.max_velocity. Null when unknown.",
    )
