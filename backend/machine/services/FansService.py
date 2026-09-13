import logging
from typing import List, Optional

from dtos.fans.FanDto import FanPins
from dtos.tools import ExtruderPins, HeaterPins
from mappers.fans.FanMapper import FanMapper
from services.fans_config_mapper import get_fans
from services.ToolsService import get_tools_service


class FansService:
    """Registers every standalone ``part`` fan's ``webgui.<id>`` HAL pin.

    ``webgui_connections.hal`` (``FanWebguiMapper``) always emits
    ``net <id>-SP <= webgui.<id>`` for a ``part`` fan, but nothing on
    the Python side used to answer that pin for a fan no heater's own
    ``fan`` cross-reference already covers (see ``.agent/component/
    fan.md``'s documented runtime gap) — LinuxCNC then refuses to
    load with "Pin 'webgui.<id>' does not exist".

    Dedup mirrors :class:`TemperatureService`'s own pattern: a fan
    already registered via a heater's nested ``fan`` field
    (``HeaterMapper.from_dict_to_HeaterPins``) is skipped here rather
    than re-registered — harmless either way (``HalPin``'s dedup guard
    silently drops a second registration) but noisy at startup.
    """

    def __init__(self):
        self._halpins_cache: Optional[List[FanPins]] = None

    def preload_hal_pins(self) -> None:
        """Queue every standalone fan's pin. Call before ``HalPin.initialize_component()``."""
        if self._halpins_cache is not None:
            return

        used_fan_ids: set[str] = set()
        for tool_pins in get_tools_service().get_halpins():
            heater_pins = tool_pins.heater if isinstance(tool_pins, ExtruderPins) else tool_pins
            if not isinstance(heater_pins, HeaterPins):
                continue
            fan_pin_name = heater_pins.fan.get_pin_name()
            # ``UnconnectedHalPin.get_pin_name()`` returns the literal
            # sentinel ``"unconnected"`` for a heater with no ``fan``
            # cross-reference at all — never a real fan id.
            if fan_pin_name and fan_pin_name != "unconnected":
                used_fan_ids.add(fan_pin_name)

        out: List[FanPins] = []
        for fan in get_fans():
            if fan.get("id") in used_fan_ids:
                continue
            fan_pins = FanMapper.from_dict_to_FanPins(fan)
            if fan_pins is not None:
                out.append(fan_pins)

        self._halpins_cache = out
        logging.info("Preloaded %d fan HAL pin mappings.", len(out))

    def get_halpins(self) -> List[FanPins]:
        if self._halpins_cache is None:
            logging.warning("get_halpins() called before preload! Forcing late initialization.")
            self.preload_hal_pins()
        return self._halpins_cache or []


_fans_service: Optional[FansService] = None


def get_fans_service() -> FansService:
    """Lazy module-level singleton, matching ``get_tools_service``."""
    global _fans_service
    if _fans_service is None:
        _fans_service = FansService()
    return _fans_service


__all__ = ["FansService", "get_fans_service"]
