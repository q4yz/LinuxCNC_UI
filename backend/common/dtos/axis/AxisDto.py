from dataclasses import dataclass
from typing import List, Optional


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
    # Axis limits from hardware.json (mm/s, mm/s²) — ``None`` when the
    # machine config predates them; never defaulted.
    max_velocity: Optional[float] = None
    max_acceleration: Optional[float] = None
