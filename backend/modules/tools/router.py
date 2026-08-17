"""HTTP router for the tools module.

The router is mounted by the registry under
``/api/v1/modules/tools``. It exposes the three endpoints that
drive the machine and operator commands:

* ``POST /tools/{id}/target`` — set the target temperature for a
  heating tool (extruder / heated_bed).
* ``POST /spindle`` — start / reverse / stop a spindle using the
  canonical ``M3 S{speed}`` / ``M4 S{speed}`` / ``M5`` codes.
* ``POST /extruder`` — extrude or retract material on a 3D-printer
  extruder axis using relative (``G91``) ``G1 E{dist} F{speed}``
  moves, restoring absolute (``G90``) mode afterwards.

The router acts as a strict anti-corruption layer. It validates
incoming HTTP payloads using Pydantic models, translates them into
internal Domain DTOs via dedicated mappers, and delegates execution
to the specialized service layer (:class:`SpindleDigitalService`,
:class:`ExtruderService`, and :class:`HeaterService`).

The router itself does not import ``hardware.*`` so the rule "no
router is allowed to import any hardware file" stays strictly enforced.

The router intentionally has no ``prefix`` argument — the registry
prefixes it when mounting.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from exceptions.http import BadRequestError, NotFoundError
from modules.tools.dtos.digital_spindle_dto import DirectionStateType
from modules.tools.mapper.digital_spindle_mapper import SpindleDigitalMapper
from modules.tools.mapper.extruder_mapper import ExtruderMapper
from modules.tools.mapper.heater_mapper import HeaterMapper
from modules.tools.models.extruder_models import ExtruderCommand
from modules.tools.models.heater_models import HeaterCommand, HeaterCommandStateResponse
from modules.tools.models.spindel_digital_models import SpindleDigitalCommand, SpindleDigitalStateResponse
from modules.tools.models.tool_models import ToolCommandResponse
from modules.tools.services.extruder_service import get_extruder_service
from modules.tools.services.heater_service import get_heater_service
from modules.tools.services.spindle_digital_service import get_spindle_digital_service
from modules.tools.services.tool_service import get_tools_service

logger = logging.getLogger("backend.modules.tools.router")




tool_service = get_tools_service()
spindle_digital_service = get_spindle_digital_service()
extruder_service = get_extruder_service()
heater_service = get_heater_service()


# ---------------------------------------------------------------------- #
# Endpoints                                                               #
# ---------------------------------------------------------------------- #

router = APIRouter(tags=["modules:tools"])

_SPINDLE_ACTIONS = {
    "forward": DirectionStateType.FORWARD,
    "backward": DirectionStateType.BACKWARD,
    "stop": DirectionStateType.IDLE,
}
_EXTRUDER_ACTIONS = {"extrude", "retract"}


@router.post(
    "/spindle",
    response_model=ToolCommandResponse,
    summary="Control SpindleDigital",
    description=(
        "Start, reverse, or stop the spindle via the canonical "
        "LinuxCNC M-codes: ``M3 S{speed}`` (forward), "
        "M4 S{speed}`` (backward), or ``M5`` (stop). The router "
        "delegates to :class:`ToolsService.control_spindle`, which "
        "switches the task into MDI mode before dispatching."
    ),
    operation_id="controlSpindle",
)
def control_spindle(cmd: SpindleDigitalCommand) -> ToolCommandResponse:
    """Handle a spindle command request."""
    if cmd.action not in _SPINDLE_ACTIONS:
        raise BadRequestError(f"Invalid spindle action: {cmd.action!r}")

    settings = SpindleDigitalMapper.from_command_to_settings_dto(cmd)
    mdi = spindle_digital_service.set_spindle(settings)

    return ToolCommandResponse(status="success", command=mdi, tool_id=cmd.tool_id)


@router.post(
    "/extruder",
    response_model=ToolCommandResponse,
    description=(
        "Extrude or retract material on the extruder axis. The "
        "router delegates to :class:`ToolsService.control_extruder`, "
        "which switches into relative distance mode (``G91``), "
        "issues a single ``G1 E{dist} F{speed}`` move — the sign "
        "of ``dist`` is inverted for the retract direction — and "
        "restores absolute mode (``G90``) so subsequent commands "
        "behave as expected."
    ),
    summary="Control Extruder",
    operation_id="controlExtruder",
)
def control_extruder(cmd: ExtruderCommand) -> ToolCommandResponse:
    """Handle an extruder command request."""
    if cmd.action not in _EXTRUDER_ACTIONS:
        raise BadRequestError(f"Invalid extruder action: {cmd.action!r}")

    settings = ExtruderMapper.from_command_to_settings_dto(cmd)
    move = extruder_service.set_extruder(settings)

    return ToolCommandResponse(status="success", command=move, tool_id=cmd.tool_id)


# ---------------------------------------------------------------------- #
# Tool target endpoint                                                     #
# ---------------------------------------------------------------------- #


@router.post("/tools/{tool_id}/target", response_model=HeaterCommandStateResponse, operation_id="setToolTarget")
def set_tool_target(tool_id: str, cmd: HeaterCommand) -> HeaterCommandStateResponse:
    """Set the target temperature for a heating tool."""
    if tool_id != cmd.tool_id:
        logger.debug("tool_id in body (%r) differs from URL (%r); URL wins", cmd.tool_id, tool_id)

    settings = HeaterMapper.from_command_to_settings_dto(cmd)

    result = heater_service.set_heater(settings)

    return HeaterCommandStateResponse(
        status="success",
        tool_id=tool_id,
        target=cmd.target,
        command=result,
    )


@router.get("/spindle/{tool_id}", response_model=SpindleDigitalStateResponse, operation_id="getSpindleState")
def get_spindle_state(tool_id: str) -> SpindleDigitalStateResponse:
    """Return the live spindle state for ``tool_id``."""
    state_dto = spindle_digital_service.get_spindle(tool_id)
    return SpindleDigitalMapper.to_state_response(state_dto)


__all__ = [
    "router",
    "SpindleDigitalCommand",
    "ExtruderCommand",
    "HeaterCommand",
    "ToolCommandResponse",
    "HeaterCommandStateResponse",
    "SpindleDigitalStateResponse",
]