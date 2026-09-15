"""SpindleDigital service — :class:`SpindleDigitalService` (MDI dispatch + state machine).

The spindle dispatch logic used to live on :class:`ToolsService` directly;
the OO refactor split it into this dedicated service so the per-spindle
state machine and MDI helpers have one clear home.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from exceptions.http import NotFoundError, BadRequestError, ConflictError
from hardware import execute_sync_cmd, get_stat_channel
from hardware.Connection import linuxcnc
from services.StateService import StateService, get_state_service, MachineState


from tools_constants import (
    M3_FORWARD,
    M4_BACKWARD,
    M5_STOP,
)
from dtos.tools.SpindleDigitalDto import (
    SpindleDigitalPins,
    SpindleDigitalSettingsDTO,
    SpindleDigitalStateDTO, DirectionStateType,
)
from services.ToolsService import ToolsService, get_tools_service
from services.MachineService import get_machine_service, MachineService

logger = logging.getLogger("backend.tools_service")

machine_service: MachineService = get_machine_service()
state_service: StateService = get_state_service()
tool_service: ToolsService = get_tools_service()



class SpindleDigitalService:
    """Single-spindle dispatch + state machine."""

    def __init__(self):
        # Dictionary to store {spindle_index: {"direction": int, "speed": float}}
        self._paused_spindle_states = {}

    def get_spindle(self, tool_id: str) -> SpindleDigitalStateDTO:
        if not isinstance(tool_id, str) or not tool_id:
            raise BadRequestError("SpindleDigital tool_id must be a non-empty string")

        try:
            return tool_service.get_state(tool_id, SpindleDigitalStateDTO)
        except KeyError as exc:
            raise NotFoundError(str(exc))
        except Exception as exc:
            raise BadRequestError(f"Failed to parse spindle {tool_id!r}: {exc}")


    def set_spindle(self, dto: SpindleDigitalSettingsDTO, ):

        pins: SpindleDigitalPins = tool_service.get_halpin(dto.id, SpindleDigitalPins)

        if not isinstance(dto, SpindleDigitalSettingsDTO):
            raise BadRequestError("SpindleDigital settings must be a SpindleSettingsDTO")
        if not isinstance(pins, SpindleDigitalPins):
            raise BadRequestError("SpindleDigital pins must be a SpindleDigitalPins record")


        if self._check_for_direction_conflict(pins, dto):
            raise ConflictError(
                f"SpindleDigital {pins.id!r} is already spinning; "
                "stop it before reversing."
            )

        if dto.state == DirectionStateType.FORWARD:
            return self._forward(pins, dto)
        if dto.state == DirectionStateType.BACKWARD:
            return self._reverse(pins, dto)
        if dto.state == DirectionStateType.STOP:
            return self._stop(pins)
        if dto.state == DirectionStateType.CONTINUE:
            return self._continue(pins, dto)

        raise BadRequestError("SpindleDigital settings must be a included")

    def _forward(self, pins: SpindleDigitalPins, dto: SpindleDigitalSettingsDTO):
        mdi = "set speed"

        current_state = state_service.get_state()

        pins.absolute_master_override.set_value(dto.master_override)
        pins.absolute_master_override_enable.set_value(dto.master_override_enable)

        if current_state in (MachineState.RUNNING, MachineState.PAUSED):
            pins.override.set_value(int(dto.override * 100))
        else:
            machine_service.ensure_mdi_mode()
            pins.override.set_value(100)
            mdi = M3_FORWARD.format(speed=dto.master_override)
            machine_service.dispatch_mdi(mdi)
        return mdi

    def _reverse(self, pins: SpindleDigitalPins, dto: SpindleDigitalSettingsDTO):
        mdi = "set speed"

        current_state = state_service.get_state()

        pins.absolute_master_override.set_value(dto.master_override)
        pins.absolute_master_override_enable.set_value(dto.master_override_enable)

        if current_state in (MachineState.RUNNING, MachineState.PAUSED):
            pins.override.set_value(int(dto.override * 100))
        else:
            machine_service.ensure_mdi_mode()
            pins.override.set_value(100)
            mdi = M4_BACKWARD.format(speed=dto.master_override)
            machine_service.dispatch_mdi(mdi)
        return mdi


    def _stop(self, pins: SpindleDigitalPins):
        machine_service.ensure_mdi_mode()
        mdi = M5_STOP
        machine_service.dispatch_mdi(mdi)
        pins.absolute_master_override_enable.set_value(False)
        return mdi


    def _check_for_direction_conflict(self, pins: SpindleDigitalPins, dto: SpindleDigitalSettingsDTO, ):
        if dto.state == DirectionStateType.FORWARD and pins.spindle_reverse.get_value():
            return True
        if dto.state == DirectionStateType.BACKWARD and pins.spindle_forward.get_value():
            return True
        return False

    def _continue(self, pins,  dto: SpindleDigitalSettingsDTO):
        pins.override.set_value(int(dto.override * 100))
        pins.absolute_master_override.set_value(dto.master_override)
        pins.absolute_master_override_enable.set_value(dto.master_override_enable)
        return ""

    def stop_all_for_pause(self) -> None:
        """Snapshot current spindle states and force them off via raw API.

        Bypasses the MDI path because the interpreter is locked during AUTO_PAUSE.
        """
        stat = get_stat_channel()
        self._paused_spindle_states.clear()

        # 1. Snapshot the state before we kill the spindle
        if stat:
            stat.poll()
            try:
                for i, sp in enumerate(stat.spindle):
                    self._paused_spindle_states[i] = {
                        "direction": sp.get("direction", 0),
                        "speed": sp.get("speed", 0.0)
                    }
            except (TypeError, AttributeError):
                self._paused_spindle_states[0] = {
                    "direction": getattr(stat, "spindle_direction", 0),
                    "speed": getattr(stat, "spindle_speed", 0.0)
                }

        # 2. Find all spindles and force them off
        spindle_ids = [
            pins.id
            for pins in tool_service.get_halpins()
            if isinstance(pins, SpindleDigitalPins)
        ]

        for tool_id in spindle_ids:
            try:
                idx = int(tool_id)
                # execute_sync_cmd(name, timeout, direction, speed, spindle_number)
                execute_sync_cmd("spindle", 0, getattr(linuxcnc, "SPINDLE_OFF", 0), 0, idx)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to stop spindle %r via raw API on pause: %s", tool_id, exc)

    def resume_all_from_pause(self) -> None:
        """Restore spindles to their pre-pause state via raw API."""
        spindle_ids = [
            pins.id
            for pins in tool_service.get_halpins()
            if isinstance(pins, SpindleDigitalPins)
        ]

        if not spindle_ids:
            return

        spindles_restarted = False

        for tool_id in spindle_ids:
            idx = int(tool_id)
            state = self._paused_spindle_states.get(idx, {"direction": 1, "speed": 0.0})

            # If it was stopped via M5 before the pause, don't spin it up
            if state["direction"] == 0:
                continue

            cmd_dir = (
                getattr(linuxcnc, "SPINDLE_REVERSE", 2)
                if state["direction"] == -1
                else getattr(linuxcnc, "SPINDLE_FORWARD", 1)
            )

            try:
                execute_sync_cmd("spindle", 0, cmd_dir, state["speed"], idx)
                spindles_restarted = True
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to restart spindle %r on resume: %s", tool_id, exc)

        if spindles_restarted:
            # Give the VFD enough time to physically reach target RPM
            time.sleep(2.0)


_spindle_digital_service: Optional[SpindleDigitalService] = None

def get_spindle_digital_service() -> SpindleDigitalService:
    """Lazy module-level singleton (tool telemetry / dispatch facade)."""
    global _spindle_digital_service
    if _spindle_digital_service is None:
        _spindle_digital_service = SpindleDigitalService()
    return _spindle_digital_service

__all__ = ["SpindleDigitalService", "get_spindle_digital_service"]
