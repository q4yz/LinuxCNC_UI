from typing import List

from pydantic import BaseModel, Field


class AxisStateResponse(BaseModel):
    """JSON response model for axis configuration.

    v2.1: identified by ``joint_number`` (the LinuxCNC ``[JOINT_N]``
    index of the axis's primary joint) plus ``joint_numbers`` (every
    joint that drives the axis). The previous ``id`` string handle
    was removed in favour of the integer ``joint_number`` — the
    runtime maps that number to a Remora stepgen channel
    ``remora.joint.{N}.*`` deterministically.
    """
    joint_number: int = Field(
        ...,
        description=(
            "Primary joint_number — the LinuxCNC [JOINT_N] index of the "
            "axis's first-listed (primary) joint. The runtime uses this "
            "to map to remora.joint.{N}.* stepgen channels."
        ),
    )
    joint_numbers: List[int] = Field(
        ...,
        description=(
            "All joint_numbers driving this axis. For a single-motor "
            "axis the list has one element equal to joint_number. "
            "Multi-motor axes (e.g. dual-motor Y) list every joint."
        ),
    )
    min_limit: float = Field(..., description="Minimum soft limit for the axis")
    max_limit: float = Field(..., description="Maximum soft limit for the axis")
