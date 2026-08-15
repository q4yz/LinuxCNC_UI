"""Spindle service — :class:`SpindleDigitalService` (MDI dispatch + state machine).

The spindle dispatch logic used to live on :class:`ToolsService` directly;
the OO refactor split it into this dedicated service so the per-spindle
state machine and MDI helpers have one clear home.
"""

from __future__ import annotations

import logging
from typing import Optional

from exceptions.http import NotFoundError, BadRequestError, ConflictError

from modules.state.service import StateService, get_state_service, MachineState

from modules.tools.config_mapper import get_digital_spindle
from modules.tools.constants import (
    DEFAULT_SPINDLE_OVERRIDE_PIN,
    M3_FORWARD,
    M4_BACKWARD,
    M5_STOP,
)
from modules.tools.dtos.digital_spindle_dto import (
    SpindleDigitalPins,
    SpindleDigitalSettingsDTO,
    SpindleDigitalStateDTO, DirectionStateType,
)
from modules.tools.mapper.digital_spindle_mapper import SpindleDigitalMapper
from services.machine_service import get_machine_service, MachineService

logger = logging.getLogger("backend.modules.tools.spindle_service")

machine_service: MachineService = get_machine_service()
state_service: StateService = get_state_service()



class SpindleDigitalService:
    """Single-spindle dispatch + state machine."""

    def get_spindle(self, tool_id: str) -> SpindleDigitalStateDTO:
        if not isinstance(tool_id, str) or not tool_id:
            raise BadRequestError("Spindle tool_id must be a non-empty string")

        try:
            return SpindleDigitalMapper.to_state_dto(SpindleDigitalMapper.from_dict_to_SpindleDigitalPins(get_digital_spindle(tool_id)))
        except KeyError as exc:
            raise NotFoundError(str(exc))
        except Exception as exc:
            raise BadRequestError(f"Failed to parse spindle {tool_id!r}: {exc}")


    def set_spindle(self, dto: SpindleDigitalSettingsDTO, ):

        pins: SpindleDigitalPins = SpindleDigitalMapper.from_dict_to_SpindleDigitalPins(get_digital_spindle(dto.id))

        if not isinstance(dto, SpindleDigitalSettingsDTO):
            raise BadRequestError("Spindle settings must be a SpindleSettingsDTO")
        if not isinstance(pins, SpindleDigitalPins):
            raise BadRequestError("Spindle pins must be a SpindleDigitalPins record")


        if self._check_for_direction_conflict(pins, dto):
            raise ConflictError(
                f"Spindle {pins.id!r} is already spinning; "
                "stop it before reversing."
            )

        if dto.state == DirectionStateType.FORWARD:
            return self._forward(pins, dto)
        if dto.state == DirectionStateType.BACKWARD:
            return self._reverse(pins, dto)
        if dto.state == DirectionStateType.IDLE:
            return self._stop()

        raise BadRequestError("Spindle settings must be a included")

    def _forward(self, pins: SpindleDigitalPins, dto: SpindleDigitalSettingsDTO):
        machine_service.ensure_mdi_mode()
        target_rpm = self._calculate_rpm(dto)
        if target_rpm == -1 :
            pins.override.set_value(dto.override)
            return f"override={dto.override}"
        mdi = M3_FORWARD.format(speed=target_rpm)
        machine_service.dispatch_mdi(mdi)
        return mdi

    def _reverse(self, pins: SpindleDigitalPins, dto: SpindleDigitalSettingsDTO):
        machine_service.ensure_mdi_mode()
        target_rpm = self._calculate_rpm(dto)
        if target_rpm == -1 :
            pins.override.set_value(dto.override)
            return f"override={dto.override}"
        mdi = M4_BACKWARD.format(speed=target_rpm)
        machine_service.dispatch_mdi(mdi)
        return mdi


    def _stop(self):
        machine_service.ensure_mdi_mode()
        mdi = M5_STOP
        machine_service.dispatch_mdi(mdi)
        return mdi

    def _calculate_rpm(self, dto: SpindleDigitalSettingsDTO) -> int:
        current_state = state_service.get_state()

        if current_state in (MachineState.RUNNING, MachineState.PAUSED):
            return self._running_mode_rpm(dto)

        if current_state in (MachineState.IDLE, MachineState.LOADED):
            return self._manual_mode_rpm(dto)
        return 0

    def _manual_mode_rpm(self, dto) -> int:
        return dto.master_override

    def _running_mode_rpm(self, dto) -> int:
        if dto.master_override_enable:
            return dto.master_override
        return -1

    def _check_for_direction_conflict(self, pins: SpindleDigitalPins, dto: SpindleDigitalSettingsDTO, ):
        if dto.state == DirectionStateType.FORWARD and pins.spindle_reverse.get_value():
            return True
        if dto.state == DirectionStateType.BACKWARD and pins.spindle_forward.get_value():
            return True
        return False

_spindle_digital_service: Optional[SpindleDigitalService] = None

def get_spindle_digital_service() -> SpindleDigitalService:
    """Lazy module-level singleton (tool telemetry / dispatch facade)."""
    global _spindle_digital_service
    if _spindle_digital_service is None:
        _spindle_digital_service = SpindleDigitalService()
    return _spindle_digital_service

__all__ = ["SpindleDigitalService", "get_spindle_digital_service"]
