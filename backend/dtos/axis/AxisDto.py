from dataclasses import dataclass
from typing import List


@dataclass(slots=True)
class AxisStateDTO:
    """Internal backend representation of static axis configuration.

    Identified by a string ``id`` (the canonical LinuxCNC letter —
    ``x``, ``y``, ``z``, ``a``, ...) and lists every driving joint as
    ``joint_numbers``. Joints (the motors) are the things keyed by
    integer ``joint_number``; the axis itself is the logical
    coordinate frame.
    """
    id: str
    joint_numbers: List[int]
    min_limit: float
    max_limit: float
