import logging
from typing import Optional

from exceptions.http import BadRequestError, NotFoundError

# Adjust import paths based on your actual structure
from modules.tools.config_mapper import get_extruder
from modules.tools.dtos.extruder_dto import ExtruderSettingsDTO, ExtruderStateDTO, ExtruderPins
from modules.tools.dtos.heater_dto import HeaterSettingsDTO
from modules.tools.mapper.extruder_mapper import ExtruderMapper
from modules.tools.services.heater_service import HeaterService
from modules.tools.services.tool_service import get_tools_service
from services.machine_service import get_machine_service

logger = logging.getLogger("backend.modules.tools.extruder_service")
machine_service = get_machine_service()
tool_service = get_tools_service()
heater_service = HeaterService()

class ExtruderService:
    """Single-extruder dispatch + state reader."""

    def get_extruder(self, tool_id: str) -> ExtruderStateDTO:
        if not isinstance(tool_id, str) or not tool_id:
            raise BadRequestError("Extruder tool_id must be a non-empty string")

        try:
            return tool_service.get_state(tool_id, ExtruderStateDTO)
        except KeyError as exc:
            raise NotFoundError(str(exc))
        except Exception as exc:
            raise BadRequestError(f"Failed to parse extruder {tool_id!r}: {exc}")

    def set_extruder(self, dto: ExtruderSettingsDTO) -> str:
        if not isinstance(dto, ExtruderSettingsDTO):
            raise BadRequestError("Extruder settings must be an ExtruderSettingsDTO")

        try:
            tool_service.get_halpin(dto.id, ExtruderPins)
        except KeyError as exc:
            raise NotFoundError(str(exc))

        # ``dto.heater`` is ``None`` when the caller chose
        # ``heater_action="noop"`` — the move runs without touching
        # the heater. ``set_heater`` still raises on out-of-range
        # targets so the validation surface stays unchanged.
        if dto.heater is not None:
            heater_service.set_heater(dto.heater)

        # 2. Extrusion Handling (Relative Distance)
        distance = float(dto.relative_distance)
        if distance == 0.0:
            return "no_action"

        machine_service.ensure_mdi_mode()
        # G91 (Relative), Extrude, G90 (Absolute) — the canonical
        # LinuxCNC/Klipper-style G-code string the dashboard's
        # ``ExtruderCard`` and ``ActivePrintWidget`` echo to
        # the operator verbatim. The ``G91`` / ``G90`` framing is
        # applied to ``machine_service`` via the channel's MDI
        # queue; the dispatched ``G1`` is what the dashboard shows.
        machine_service.dispatch_mdi("G91")
        mdi_command = f"G1 E{distance} F{dto.speed}"
        machine_service.dispatch_mdi(mdi_command)
        machine_service.dispatch_mdi("G90")
        return mdi_command

_extruder_service: Optional[ExtruderService] = None

def get_extruder_service() -> ExtruderService:
    """Lazy module-level singleton (tool telemetry / dispatch facade)."""
    global _extruder_service
    if _extruder_service is None:
        _extruder_service = ExtruderService()
    return _extruder_service

__all__ = ["ExtruderService", "get_extruder_service"]