from dataclasses import dataclass
from typing import List


@dataclass(slots=True)
class AxisStateDTO:
    """Internal backend representation of static axis configuration.

    v2.1: identified by ``joint_number`` (the LinuxCNC ``[JOINT_N]``
    index of the axis's primary joint) plus ``joint_numbers`` (every
    joint that drives the axis). The previous ``id`` string handle
    was removed in favour of the integer ``joint_number`` so the
    runtime maps directly to a Remora stepgen channel without going
    through a separate string identifier.
    """
    joint_number: int
    joint_numbers: List[int]
    min_limit: float
    max_limit: float
