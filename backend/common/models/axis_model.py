from typing import List

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
    joint_numbers: List[int] = Field(
        ...,
        description=(
            "All joint_numbers driving this axis. For a single-motor "
            "axis the list has one element. Multi-motor axes (e.g. "
            "dual-motor Y) list every joint."
        ),
    )
    min_limit: float = Field(..., description="Minimum soft limit for the axis")
    max_limit: float = Field(..., description="Maximum soft limit for the axis")
