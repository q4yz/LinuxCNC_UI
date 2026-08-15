from dataclasses import dataclass
from typing import Dict, Any, Optional, Literal

from dtos.HalPin import HalPin, UnconnectedHalPin, DynamicHalPin, StaticHalPin


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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpindleDigitalPins":
        tool_id = str(data["id"])
        suffix = tool_id.replace("spindle_digital", "")

        return cls(
            id=tool_id,
            spindle_at_speed = DynamicHalPin(f"spindle-at-speed{suffix}"),
            target_rpm = DynamicHalPin(f"TargetRpm{suffix}"),
            actual_rpm = DynamicHalPin(f"rpm-out{suffix}"),
            is_connected = DynamicHalPin(f"is-connected{suffix}"),
            error_count = DynamicHalPin(f"error-count{suffix}"),
            last_error = DynamicHalPin(f"last-error{suffix}"),
            min_rpm= StaticHalPin(cls._as_optional_int(data.get("min_rpm")) or 0) ,
            max_rpm=StaticHalPin(cls._as_optional_int(data.get("max_rpm")) or 24000) ,
        )


    @classmethod
    def _as_optional_int(cls, value: object) -> Optional[int]:
        if isinstance(value, (int, float)):
            return int(value)

        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            try:
                return int(float(value))
            except ValueError:
                return None
        return None

    def to_state_dto(self) -> "SpindleStateDTO":
        """Evaluates all pins and returns a snapshot of the current spindle state."""

        # Internal safe-casting helpers
        def _as_float(value: Any) -> float:
            try:
                return float(value) if value is not None else 0.0
            except (ValueError, TypeError):
                return 0.0

        def _as_int(value: Any) -> int:
            try:
                return int(value) if value is not None else 0
            except (ValueError, TypeError):
                return 0

        def _as_bool(value: Any) -> bool:
            return bool(value) if value is not None else False

        def _as_str(value: Any) -> str:
            return str(value) if value is not None else ""

        return SpindleStateDTO(
            id=self.id,
            target_rpm=_as_float(self.target_rpm.get_value()),
            actual_rpm=_as_float(self.actual_rpm.get_value()),
            is_connected=_as_bool(self.is_connected.get_value()),
            error_count=_as_int(self.error_count.get_value()),
            last_error=_as_str(self.last_error.get_value()),
            spindle_at_speed=_as_bool(self.spindle_at_speed.get_value()),
            min_rpm=_as_float(self.min_rpm.get_value()),
            max_rpm=_as_float(self.max_rpm.get_value()),
        )

@dataclass(frozen=True, slots=True)
class SpindleStateDTO:
    id: str
    target_rpm: float = 0.0
    actual_rpm: float = 0.0
    is_connected: bool = False
    error_count: int = 0
    last_error: str = ""
    spindle_at_speed: bool = False
    min_rpm: float = 0.0
    max_rpm: float = 0.0


@dataclass(slots=True)
class SpindleSettingsDTO:
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
        Relative override factor (``0.0``–``2.0``; ``1.0`` = 100%).
        Written to ``halui.spindle.override.scale`` before every M-code
        dispatch. Ignored if ``master_override_enable`` is ``True``.
    master_override_enable:
        If enabled, bypasses standard ``speed`` and ``override`` scaling
        and directly forces the spindle to the ``master_override`` RPM.
    state:
        The commanded spindle action. ``"stop"`` halts the spindle (``M5``);
        ``"forward"`` starts it clockwise (``M3``); and ``"reverse"`` starts
        it counter-clockwise (``M4``). Mid-spin direction changes raise
        :class:`HTTPException` ``409`` — the operator must stop first.
    """

    speed: int
    master_override: int
    override: float = 1.0
    master_override_enable: bool = False
    state: Literal["forward", "reverse", "stop"] = "forward"