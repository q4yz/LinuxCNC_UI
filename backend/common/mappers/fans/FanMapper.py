from typing import Any, Dict, Optional

from dtos.fans.FanDto import FanPins
from dtos.pins.HalPin import HalDataType
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin


class FanMapper:

    @classmethod
    def from_dict_to_FanPins(cls, data: Dict[str, Any]) -> Optional[FanPins]:
        """Build a standalone ``part`` fan's HAL surface.

        ``ReadWriteDynamicHalPin`` (HAL_OUT), same as a heater's own
        nested ``fan`` field (``HeaterMapper``) — the fan's speed is
        *driven by* webgui, matching ``FanWebguiMapper``'s
        ``net <id>-SP <= webgui.<id>``. This is for a fan no heater
        already references (see fan.md's still-open runtime gap); a
        ``kind: "heater"`` fan gets no pin at all here — it is never
        operator-commandable (fan.md § 1's control-model table).
        """
        if data.get("kind") != "part":
            return None
        fan_id = str(data["id"])
        return FanPins(
            id=fan_id,
            speed=ReadWriteDynamicHalPin(fan_id, HalDataType.FLOAT, "Fan speed setpoint (0.0-1.0)"),
        )


__all__ = ["FanMapper"]
