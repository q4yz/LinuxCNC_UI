import logging
from typing import Optional

from dtos.sensors.TemperatureDto import TemperatureStateDto
from temperature_config_mapper import get_temperature_sensors

from factories.temperature.TemperatureStateFactory import TemperatureStateFactory
from mappers.temperature.TemperatureSensorMapper import TemperatureSensorMapper
from tools_config_mapper import get_all_heater
from dtos.tools import HeaterStateDTO
from mappers.tools.HeaterMapper import HeaterMapper


class TemperatureService:


    def __init__(self):
        self._halpins_cache = None

    def preload_hal_pins(self) -> None:
        """
        Forces the factory to build the DTOs.
        This queues the pins in HalPin._pending_pins.
        Must be called at startup BEFORE HalPin.initialize_component()
        """
        if self._halpins_cache is not None:
            return

        out = []
        used_sensor_ids = set()

        heaters = get_all_heater()
        for tool in heaters:
            pin_map = HeaterMapper.from_dict_to_HeaterPins(tool)
            if pin_map is not None:
                out.append(pin_map)
                sensor_id = tool.get("sensor") or tool.get("id")
                if sensor_id:
                    used_sensor_ids.add(sensor_id)

        sensors = get_temperature_sensors()
        for sensor in sensors:
            sensor_id = sensor.get("id")

            if sensor_id in used_sensor_ids:
                continue

            pin_map = TemperatureSensorMapper.from_dict_to_TemperaturePins(sensor)
            if pin_map is not None:
                out.append(pin_map)

        self._halpins_cache = out
        logging.info("Preloaded %d temperature HAL pin mappings.", len(out))

    def get_halpins(self) -> list:
        """Returns the pre-built DTOs for your API routes."""
        if self._halpins_cache is None:
            logging.warning("get_halpins() called before preload! Forcing late initialization.")
            self.preload_hal_pins()

        return self._halpins_cache

    def get_states(self) -> list[HeaterStateDTO | TemperatureStateDto]:
        return [TemperatureStateFactory.create(halpin) for halpin in self.get_halpins()]


_temperature_service: Optional[TemperatureService] = None

def get_temperature_service() -> TemperatureService:
    """Lazy module-level singleton (tool telemetry / dispatch facade)."""
    global _temperature_service
    if _temperature_service is None:
        _temperature_service = TemperatureService()
    return _temperature_service

__all__ = ["TemperatureService", "get_temperature_service"]