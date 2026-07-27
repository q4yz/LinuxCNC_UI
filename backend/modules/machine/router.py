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

* ``POST /state``  — toggle machine E-Stop or Power state.
* ``POST /mode``   — change task mode (``manual``, ``auto``, ``mdi``).
* ``POST /home``   — home a single axis or all axes.
* ``POST /mdi``    — execute a single MDI command.
* ``POST /print``  — load and start a G-code program.
* ``POST /pause``  — pause the active G-code program.
* ``POST /resume`` — resume the paused G-code program.
* ``POST /stop``   — abort the active G-code program.

The router takes no ``prefix`` argument — the registry prefixes it
when mounting under ``/api/v1/modules/machine``.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from hardware import execute_sync_cmd, get_machine_stat, linuxcnc
from services.console_logger import LogLevel, get_console_logger

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


class PrintCommand(BaseModel):
    """Pydantic model for loading and starting a G-code program."""

    filename: str = Field(
        ...,
        min_length=1,
        description="Path to the G-code program to load and execute",
    )


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


def _require_machine_ready() -> None:
    """Reject program-control commands unless the machine is safely powered.

    ``linuxcnc.stat`` objects are snapshots, so poll immediately before
    checking E-Stop and power state.  The explicit E-Stop check also covers
    mock/adapter implementations that expose ``estop`` independently from
    ``task_state``.
    """
    machine_stat = get_machine_stat()
    machine_stat.poll()

    task_state = getattr(machine_stat, "task_state", None)
    estop = getattr(machine_stat, "estop", 0)
    estop_active = isinstance(estop, (bool, int)) and bool(estop)

    if task_state == getattr(linuxcnc, "STATE_ESTOP", 1) or estop_active:
        raise HTTPException(
            status_code=400,
            detail="Cannot control a program while the machine is in E-Stop.",
        )
    if task_state != getattr(linuxcnc, "STATE_ON", 4):
        raise HTTPException(
            status_code=400,
            detail="Cannot control a program while the machine is powered off.",
        )


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
    # Mirror the command to the persistent console history so the
    # on-disk log shows every command the operator issued, even if
    # the in-browser console clears its buffer.
    console_logger = get_console_logger()
    console_logger.log_command(cmd.command)
    try:
        execute_sync_cmd("mode", 5, getattr(linuxcnc, "MODE_MDI", 3))
        result = execute_sync_cmd("mdi", 0, cmd.command)
        console_logger.log_response(
            f"Executed: {cmd.command}",
            level=LogLevel.INFO,
        )
        return StatusResponse(status=result.get("status", "success"))
    except HTTPException as exc:
        console_logger.log_response(
            f"Error: {exc.detail}",
            level=LogLevel.ERROR,
        )
        raise


@router.post(
    "/print",
    summary="Start G-Code Print",
    description=(
        "Switch to automatic mode, load the requested G-code file, and "
        "start execution from its first line."
    ),
    operation_id="startPrint",
    response_model=StatusResponse,
)
def start_print(cmd: PrintCommand) -> StatusResponse:
    """Load ``cmd.filename`` and start it in LinuxCNC AUTO mode."""
    _require_machine_ready()
    if not cmd.filename.strip():
        raise HTTPException(status_code=400, detail="Filename cannot be blank.")

    execute_sync_cmd("mode", 5, getattr(linuxcnc, "MODE_AUTO", 2))
    execute_sync_cmd("program_open", 0, cmd.filename)
    result = execute_sync_cmd(
        "auto", 0, getattr(linuxcnc, "AUTO_RUN", 0), 0
    )
    return StatusResponse(status=result.get("status", "success"))


@router.post(
    "/pause",
    summary="Pause G-Code Print",
    description="Pause execution of the active G-code program.",
    operation_id="pausePrint",
    response_model=StatusResponse,
)
def pause_print() -> StatusResponse:
    """Pause the active program after checking machine safety state."""
    _require_machine_ready()
    result = execute_sync_cmd(
        "auto", 0, getattr(linuxcnc, "AUTO_PAUSE", 1)
    )
    return StatusResponse(status=result.get("status", "success"))


@router.post(
    "/resume",
    summary="Resume G-Code Print",
    description="Resume execution of a paused G-code program.",
    operation_id="resumePrint",
    response_model=StatusResponse,
)
def resume_print() -> StatusResponse:
    """Resume the paused program after checking machine safety state."""
    _require_machine_ready()
    result = execute_sync_cmd(
        "auto", 0, getattr(linuxcnc, "AUTO_RESUME", 2)
    )
    return StatusResponse(status=result.get("status", "success"))


@router.post(
    "/stop",
    summary="Stop G-Code Print",
    description="Abort execution of the active G-code program.",
    operation_id="stopPrint",
    response_model=StatusResponse,
)
def stop_print() -> StatusResponse:
    """Abort the active program after checking machine safety state."""
    _require_machine_ready()
    result = execute_sync_cmd("abort", 0)
    return StatusResponse(status=result.get("status", "success"))


__all__ = [
    "router",
    "set_state",
    "set_mode",
    "home_axis",
    "run_mdi",
    "start_print",
    "pause_print",
    "resume_print",
    "stop_print",
    "StateCommand",
    "ModeCommand",
    "HomeCommand",
    "MdiCommand",
    "PrintCommand",
    "StatusResponse",
]
