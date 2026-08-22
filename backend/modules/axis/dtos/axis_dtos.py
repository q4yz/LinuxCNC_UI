from dataclasses import dataclass
from typing import List


@dataclass(slots=True)
class AxisStateDTO:
    """Internal backend representation of static axis configuration."""
    id: str
    joints: List[int]
    min_limit: float
    max_limit: float


