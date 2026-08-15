import logging

from exceptions.http import BadRequestError, NotFoundError
from modules.tools.config_mapper import get_heater
from modules.tools.dtos.heater_dto import HeaterSettingsDTO, HeaterStateDTO, HeaterPins
from modules.tools.mapper.heater_mapper import HeaterMapper

logger = logging.getLogger("backend.modules.tools.heater_service")

class HeaterService:

    def get_heater(self, tool_id: str) -> HeaterStateDTO:
        if not isinstance(tool_id, str) or not tool_id:
            raise BadRequestError("Heater tool_id must be a non-empty string")

        try:
            return HeaterMapper.to_state_dto(HeaterMapper.from_dict_to_HeaterPins(get_heater(tool_id)))
        except KeyError as exc:
            raise NotFoundError(str(exc))
        except Exception as exc:
            raise BadRequestError(f"Failed to parse heater {tool_id!r}: {exc}")


    def set_heater(self, dto : HeaterSettingsDTO) -> str:

        pins: HeaterPins =HeaterMapper.from_dict_to_HeaterPins(get_heater(dto.id))

        if not isinstance(dto, HeaterSettingsDTO):
            raise BadRequestError("Heater settings must be a HeaterSettingsDTO")
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
