import logging
from typing import Optional

from exceptions.http import BadRequestError, NotFoundError
from modules.tools.config_mapper import get_heater
from modules.tools.dtos.heater_dto import HeaterSettingsDTO, HeaterStateDTO, HeaterPins
from modules.tools.mapper.heater_mapper import HeaterMapper
from modules.tools.services.tool_service import get_tools_service

logger = logging.getLogger("backend.modules.tools.heater_service")

tool_service = get_tools_service()

class HeaterService:

    def get_heater(self, tool_id: str) -> HeaterStateDTO:
        if not isinstance(tool_id, str) or not tool_id:
            raise BadRequestError("Heater tool_id must be a non-empty string")

        try:
            return tool_service.get_state(tool_id, HeaterStateDTO)
        except KeyError as exc:
            raise NotFoundError(str(exc))
        except Exception as exc:
            raise BadRequestError(f"Failed to parse heater {tool_id!r}: {exc}")


    def set_heater(self, dto : HeaterSettingsDTO) -> str:

        if not isinstance(dto, HeaterSettingsDTO):
            raise BadRequestError("Heater settings must be a HeaterSettingsDTO")

        try:
            pins: HeaterPins = tool_service.get_halpin(dto.id, HeaterPins)
        except KeyError as exc:
            raise NotFoundError(str(exc))

        if not isinstance(pins, HeaterPins):
            raise BadRequestError("Heater pins must be a HeaterPins record")

        target = float(dto.target_temperature) if dto.enable else 0.0

        min_temp = pins.min_temp.get_value() or 0.0
        max_temp = pins.max_temp.get_value() or 300.0

        if target > max_temp:
            raise BadRequestError(f"Target temperature {target} exceeds hardware maximum of {max_temp}")
        if target < min_temp and target != 0.0:
            raise BadRequestError(f"Target temperature {target} is below hardware minimum of {min_temp}")

        pins.target_temperature.set_value(target)
        return f"target_temperature={target}"

_heater_service: Optional[HeaterService] = None

def get_heater_service() -> HeaterService:
    """Lazy module-level singleton (tool telemetry / dispatch facade)."""
    global _heater_service
    if _heater_service is None:
        _heater_service = HeaterService()
    return _heater_service

__all__ = ["HeaterService", "get_heater_service"]