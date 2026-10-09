from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class SpeedOverrideDTO:
    """Live speed override state, read from LinuxCNC's status channel.

    * ``feed_override`` — ``stat.feedrate``: the feed override as a
      fraction (``1.0`` = 100 %). Set via ``command.feedrate``.
    * ``max_velocity`` — ``stat.max_velocity``: the absolute trajectory
      speed cap in mm/s. Set via ``command.maxvel``.

    ``None`` when LinuxCNC is not connected or reports nothing usable —
    never a guessed default.
    """
    feed_override: Optional[float] = None
    max_velocity: Optional[float] = None
