from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple


# ---------------------------------------------------------------------------
# Domain Enums
# ---------------------------------------------------------------------------

class MachineState(str, Enum):
    """Operator-facing machine state.

    Mirrors ``frontend/src/stores/stateFacade.js::SystemState``.
    """
    OFFLINE = "offline"
    ESTOP = "estop"
    POWER_OFF = "power_off"
    IDLE = "idle"
    LOADED = "loaded"
    RUNNING = "running"
    PAUSED = "paused"
    FAILURE = "failure"


# ---------------------------------------------------------------------------
# State DTOs
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MachineStateSnapshotDTO:
    """Domain DTO representing the immutable snapshot of the machine's state."""

    state: MachineState
    raw_task_state: int
    raw_estop: int
    raw_interp_state: int

    # Use defaults for missing telemetry
    file: str = ""
    # Use a tuple instead of a list because frozen dataclasses require immutable fields
    homed: Tuple[int, ...] = field(default_factory=lambda: (0, 0, 0))