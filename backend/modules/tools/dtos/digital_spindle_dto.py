from dataclasses import dataclass
from enum import Enum
from dtos.HalPin import HalPin, UnconnectedHalPin

class DirectionStateType(str, Enum):
    IDLE = "idle"
    FORWARD = "forward"
    BACKWARD = "backward"

@dataclass(frozen=True, slots=True)
class SpindleDigitalPins:
    id: str
    target_rpm: HalPin = UnconnectedHalPin()
    actual_rpm: HalPin = UnconnectedHalPin()
    is_connected: HalPin = UnconnectedHalPin()
    error_count: HalPin = UnconnectedHalPin()
    last_error: HalPin = UnconnectedHalPin()
    spindle_at_speed: HalPin = UnconnectedHalPin()
    min_rpm: HalPin = UnconnectedHalPin()
    max_rpm: HalPin = UnconnectedHalPin()
    spindle_forward : HalPin = UnconnectedHalPin()
    spindle_reverse : HalPin = UnconnectedHalPin()
    override: HalPin = UnconnectedHalPin()

@dataclass(frozen=True, slots=True)
class SpindleDigitalStateDTO:
    id: str
    target_rpm: float = 0.0
    actual_rpm: float = 0.0
    is_connected: bool = False
    error_count: int = 0
    last_error: str = ""
    spindle_at_speed: bool = False
    min_rpm: float = 0.0
    max_rpm: float = 0.0
    spindle_forward: bool = False
    spindle_reverse: bool = False
    override: float = 0.0


@dataclass(slots=True)
class SpindleDigitalSettingsDTO:
    """Single entry-point payload for spindle control.

    The state machine in :meth:`ToolsService.set_spindle_speed`
    consumes every field; the legacy ``POST /spindle`` endpoint
    translates its vocabulary into this DTO before delegating.

    Attributes
    ----------
    speed:
        Target RPM when ``state`` is ``"forward"`` or ``"reverse"``.
        Ignored when ``state == "stop"`` or if ``master_override_enable``
        is ``True``. Clamped to ``0..200_000`` by the router's Pydantic model.
    master_override:
        Absolute target RPM used exclusively when ``master_override_enable``
        is ``True``.
    override:
        Relative override factor (``0.0``ÔÇô``2.0``; ``1.0`` = 100%).
        Written to ``halui.spindle.override.scale`` before every M-code
        dispatch. Ignored if ``master_override_enable`` is ``True``.
    master_override_enable:
        If enabled, bypasses standard ``speed`` and ``override`` scaling
        and directly forces the spindle to the ``master_override`` RPM.
    state:
        The commanded spindle action. ``"stop"`` halts the spindle (``M5``);
        ``"forward"`` starts it clockwise (``M3``); and ``"reverse"`` starts
        it counter-clockwise (``M4``). Mid-spin direction changes raise
        :class:`HTTPException` ``409`` ÔÇö the operator must stop first.
    """
    id: str
    speed: int
    master_override: int
    override: float = 1.0
    master_override_enable: bool = False
    state: DirectionStateType = DirectionStateType.IDLE
