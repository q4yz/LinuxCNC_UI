from typing import Optional

from modules.temperature.config_mapper import get_temperature_sensors
from modules.temperature.dtos.temperature_dto import SensorStateDto
from modules.temperature.factory.temperature_state_factory import TemperatureStateFactory
from modules.temperature.mapper.temperature_mapper import TemperatureSensorMapper
from modules.tools.config_mapper import get_all_heater
from modules.tools.dtos import HeaterStateDTO
from modules.tools.mapper.heater_mapper import HeaterMapper


class TemperatureService:


    def __init__(self):
        self._halpins_cache = None

    def get_halpins(self) -> list:


        if self._halpins_cache is not None:
            return self._halpins_cache

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
        return self._halpins_cache


    def get_states(self) -> list[HeaterStateDTO | SensorStateDto ]:
        return [TemperatureStateFactory.create(halpin) for halpin in self.get_halpins()]


_temperature_service: Optional[TemperatureService] = None

def get_temperature_service() -> TemperatureService:
    """Lazy module-level singleton (tool telemetry / dispatch facade)."""
    global _temperature_service
    if _temperature_service is None:
        _temperature_service = TemperatureService()
    return _temperature_service

__all__ = ["TemperatureService", "get_temperature_service"]