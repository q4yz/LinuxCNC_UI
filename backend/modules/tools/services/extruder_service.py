import logging
from typing import Optional

from exceptions.http import BadRequestError, NotFoundError

# Adjust import paths based on your actual structure
from modules.tools.config_mapper import get_extruder
from modules.tools.dtos.extruder_dto import ExtruderSettingsDTO, ExtruderStateDTO, ExtruderPins
from modules.tools.dtos.heater_dto import HeaterSettingsDTO
from modules.tools.mapper.extruder_mapper import ExtruderMapper
from modules.tools.services.heater_service import HeaterService
from services.machine_service import get_machine_service

logger = logging.getLogger("backend.modules.tools.extruder_service")
machine_service = get_machine_service()

heater_service = HeaterService()

class ExtruderService:
    """Single-extruder dispatch + state reader."""

    def get_extruder(self, tool_id: str) -> ExtruderStateDTO:
        if not isinstance(tool_id, str) or not tool_id:
            raise BadRequestError("Extruder tool_id must be a non-empty string")

        try:
            raw_extruder = get_extruder(tool_id)
            pins = ExtruderMapper.from_dict_to_ExtruderPins(raw_extruder)
            return ExtruderMapper.to_state_dto(pins)
        except KeyError as exc:
            raise NotFoundError(str(exc))
        except Exception as exc:
            raise BadRequestError(f"Failed to parse extruder {tool_id!r}: {exc}")

    def set_extruder(self, dto: ExtruderSettingsDTO) -> str:
        if not isinstance(dto, ExtruderSettingsDTO):
            raise BadRequestError("Extruder settings must be an ExtruderSettingsDTO")

        try:
            raw_extruder = get_extruder(dto.id)
            pins: ExtruderPins = ExtruderMapper.from_dict_to_ExtruderPins(raw_extruder)
        except KeyError as exc:
            raise NotFoundError(str(exc))

        actions_taken = []

        heater_result = heater_service.set_heater(dto.heater)
        actions_taken.append(heater_result)

        # 2. Extrusion Handling (Relative Distance)
        distance = float(dto.relative_distance)
        if distance != 0.0:
            machine_service.ensure_mdi_mode()
            # G91 (Relative), Extrude, G90 (Absolute)
            mdi_command = f"G91 G1 A{distance} G90"
            machine_service.dispatch_mdi(mdi_command)
            actions_taken.append(f"extruded={distance}")

        return ", ".join(actions_taken) if actions_taken else "no_action"

_extruder_service: Optional[ExtruderService] = None

def get_extruder_service() -> ExtruderService:
    """Lazy module-level singleton (tool telemetry / dispatch facade)."""
    global _extruder_service
    if _extruder_service is None:
        _extruder_service = ExtruderService()
    return _extruder_service

__all__ = ["ExtruderService", "get_extruder_service"]