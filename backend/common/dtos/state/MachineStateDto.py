from enum import Enum


class MachineState(str, Enum):
    """Operator-facing machine state.

    Mirrors ``frontend/src/stores/stateFacade.js::SystemState``. This
    is the canonical home — ``services.StateService`` re-exports it
    for its existing importers (``SpindleDigitalService``, tests)
    rather than defining its own copy.
    """
    OFFLINE = "offline"
    ESTOP = "estop"
    POWER_OFF = "power_off"
    IDLE = "idle"
    LOADED = "loaded"
    RUNNING = "running"
    PAUSED = "paused"
    FAILURE = "failure"
