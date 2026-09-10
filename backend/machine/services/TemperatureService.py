import logging
from typing import List, Optional, Union

from dtos.sensors.TemperatureDto import TemperatureStateDto, TemperaturePin
from services.temperature_config_mapper import get_temperature_sensors

from factories.temperature.TemperatureStateFactory import TemperatureStateFactory
from mappers.temperature.TemperatureSensorMapper import TemperatureSensorMapper
from dtos.tools import ExtruderPins, HeaterStateDTO, HeaterPins
from services.ToolsService import get_tools_service


class TemperatureService:


    def __init__(self):
        self._halpins_cache: Optional[List[Union[HeaterPins, TemperaturePin]]] = None

    def preload_hal_pins(self) -> None:
        """
        Forces the factory to build the DTOs.
        This queues the pins in HalPin._pending_pins.
        Must be called at startup BEFORE HalPin.initialize_component()

        Heater-linked readings are sourced from :class:`ToolsService`'s
        own cache (``machine/main.py`` always preloads it first) rather
        than calling :class:`HeaterMapper` a second time here. Building
        a second, independent set of ``HeaterPins`` used to re-register
        the exact same HAL pin names — harmless (``HalPin``'s own dedup
        guard silently drops the second registration) but noisy: every
        startup logged a "double registration" warning for every
        heater's three pins.
        """
        if self._halpins_cache is not None:
            return

        out: List[Union[HeaterPins, TemperaturePin]] = []
        used_sensor_ids: set[str] = set()

        for tool_pins in get_tools_service().get_halpins():
            heater_pins = tool_pins.heater if isinstance(tool_pins, ExtruderPins) else tool_pins
            if not isinstance(heater_pins, HeaterPins):
                continue
            out.append(heater_pins)
            used_sensor_ids.add(heater_pins.actual_temperature.get_pin_name())

        sensors = get_temperature_sensors()
        for sensor in sensors:
            sensor_id = sensor.get("id")

            if sensor_id in used_sensor_ids:
                continue

            sensor_pin_map = TemperatureSensorMapper.from_dict_to_TemperaturePins(sensor)
            if sensor_pin_map is not None:
                out.append(sensor_pin_map)

        self._halpins_cache = out
        logging.info("Preloaded %d temperature HAL pin mappings.", len(out))

    def get_halpins(self) -> List[Union[HeaterPins, TemperaturePin]]:
        """Returns the pre-built DTOs for your API routes."""
        if self._halpins_cache is None:
            logging.warning("get_halpins() called before preload! Forcing late initialization.")
            self.preload_hal_pins()

        return self._halpins_cache or []

    def get_states(self) -> list[HeaterStateDTO | TemperatureStateDto]:
        states = (TemperatureStateFactory.create(halpin) for halpin in self.get_halpins())
        return [state for state in states if state is not None]


_temperature_service: Optional[TemperatureService] = None

def get_temperature_service() -> TemperatureService:
    """Lazy module-level singleton (tool telemetry / dispatch facade)."""
    global _temperature_service
    if _temperature_service is None:
        _temperature_service = TemperatureService()
    return _temperature_service

__all__ = ["TemperatureService", "get_temperature_service"]