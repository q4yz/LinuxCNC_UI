"""HTTP router for the machine module.

This router owns the axis / state / mode / home / MDI endpoints that
were previously defined in ``backend/routers/machine.py``. The
``set_temperature`` endpoint moved to the temperature module (issue
#03). The jog endpoints live in :mod:`backend.modules.machine.jog`,
which shares this package so the keep-alive watchdog can read the
module-private ``_active_jogs`` map without crossing package
boundaries.

Endpoints
---------

* ``POST /state`` — toggle machine E-Stop or Power state.
* ``POST /mode``  — change task mode (``manual``, ``auto``, ``mdi``).
* ``POST /home``  — home a single axis or all axes.
* ``POST /mdi``   — execute a single MDI command.

The router takes no ``prefix`` argument — the registry prefixes it
when mounting under ``/api/v1/modules/machine``.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from hardware import execute_sync_cmd, linuxcnc

logger = logging.getLogger("backend.modules.machine.router")


# ---------------------------------------------------------------------- #
# Pydantic request / response models                                      #
# ---------------------------------------------------------------------- #


class StateCommand(BaseModel):
    """Pydantic model for setting machine power state."""

    state: str = Field(
        ...,
        description=(
            "Target machine state: 'on', 'off', 'estop', or 'estop_reset'"
        ),
    )


class ModeCommand(BaseModel):
    """Pydantic model for setting machine task mode."""

    mode: str = Field(
        ...,
        description="Target task mode: 'manual', 'mdi', or 'auto'",
    )


class HomeCommand(BaseModel):
    """Pydantic model for homing an axis."""

    axis: int = Field(
        ...,
        description=(
            "Axis index to home (0=X, 1=Y, 2=Z). Use -1 to home all axes."
        ),
    )


class MdiCommand(BaseModel):
    """Pydantic model for executing MDI commands."""

    command: str = Field(..., description="G-code / MDI command string to execute")


class StatusResponse(BaseModel):
    """Generic response model for endpoints that return a status string."""

    status: str = Field(
        ...,
        description=(
            "Outcome reported by the hardware layer (e.g., 'success')"
        ),
    )


# ---------------------------------------------------------------------- #
# Endpoints                                                              #
# ---------------------------------------------------------------------- #


router = APIRouter(tags=["modules:machine"])


@router.post(
    "/state",
    summary="Set Machine State",
    description="Toggle machine E-Stop or Power state.",
    operation_id="setMachineState",
    response_model=StatusResponse,
)
def set_state(cmd: StateCommand) -> StatusResponse:
    """Set the machine's overall state (ESTOP, power, …)."""
    states = {
        "on": getattr(linuxcnc, "STATE_ON", 4),
        "off": getattr(linuxcnc, "STATE_OFF", 3),
        "estop": getattr(linuxcnc, "STATE_ESTOP", 1),
        "estop_reset": getattr(linuxcnc, "STATE_ESTOP_RESET", 2),
    }
    if cmd.state not in states:
        raise HTTPException(status_code=400, detail="Invalid state")
    result = execute_sync_cmd("state", 3, states[cmd.state])
    return StatusResponse(status=result.get("status", "success"))


@router.post(
    "/mode",
    summary="Set Machine Mode",
    description="Change the machine task mode (manual, auto, mdi).",
    operation_id="setMachineMode",
    response_model=StatusResponse,
)
def set_mode(cmd: ModeCommand) -> StatusResponse:
    """Change the task mode."""
    modes = {
        "manual": getattr(linuxcnc, "MODE_MANUAL", 1),
        "auto": getattr(linuxcnc, "MODE_AUTO", 2),
        "mdi": getattr(linuxcnc, "MODE_MDI", 3),
    }
    if cmd.mode not in modes:
        raise HTTPException(status_code=400, detail="Invalid mode")
    result = execute_sync_cmd("mode", 5, modes[cmd.mode])
    return StatusResponse(status=result.get("status", "success"))


@router.post(
    "/home",
    summary="Home Axis",
    description="Home a specific axis, or all axes if axis=-1.",
    operation_id="homeAxis",
    response_model=StatusResponse,
)
def home_axis(cmd: HomeCommand) -> StatusResponse:
    """Home the requested axis (or all of them if ``cmd.axis == -1``)."""
    execute_sync_cmd("mode", 0, getattr(linuxcnc, "MODE_MANUAL", 1))

    if cmd.axis == -1:
        # Assuming 3 axes (X, Y, Z) for baseline.
        for i in range(3):
            execute_sync_cmd("home", 3, i)
        return StatusResponse(status="success")

    result = execute_sync_cmd("home", 3, cmd.axis)
    return StatusResponse(status=result.get("status", "success"))


@router.post(
    "/mdi",
    summary="Run MDI Command",
    description=(
        "Execute a single MDI (G-Code) command. Automatically "
        "switches the machine to MDI mode before dispatching the "
        "command to the hardware layer."
    ),
    operation_id="runMdiCommand",
    response_model=StatusResponse,
)
def run_mdi(cmd: MdiCommand) -> StatusResponse:
    """Execute a single MDI command."""
    logger.info("Running MDI: %s", cmd.command)
    execute_sync_cmd("mode", 5, getattr(linuxcnc, "MODE_MDI", 3))
    result = execute_sync_cmd("mdi", 0, cmd.command)
    return StatusResponse(status=result.get("status", "success"))


__all__ = [
    "router",
    "set_state",
    "set_mode",
    "home_axis",
    "run_mdi",
    "StateCommand",
    "ModeCommand",
    "HomeCommand",
    "MdiCommand",
    "StatusResponse",
]
