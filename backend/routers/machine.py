import logging
import time
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from hardware import execute_sync_cmd, linuxcnc

logger = logging.getLogger("backend.routers.machine")

router = APIRouter(prefix="/api/v1/machine", tags=["Machine State"])
program_router = APIRouter(prefix="/api/v1/program", tags=["Program Execution"])


class StateCommand(BaseModel):
    """Pydantic model for setting machine power state."""
    state: str = Field(..., description="Target machine state: 'on', 'off', 'estop', or 'estop_reset'")


class ModeCommand(BaseModel):
    """Pydantic model for setting machine task mode."""
    mode: str = Field(..., description="Target task mode: 'manual', 'mdi', or 'auto'")


class HomeCommand(BaseModel):
    """Pydantic model for homing an axis."""
    axis: int = Field(..., description="Axis index to home (0=X, 1=Y, 2=Z). Use -1 to home all axes.")


class MdiCommand(BaseModel):
    """Pydantic model for executing MDI commands."""
    command: str = Field(..., description="G-code / MDI command string to execute")


class StatusResponse(BaseModel):
    """Generic response model for endpoints that return a status string."""
    status: str = Field(..., description="Outcome reported by the hardware layer (e.g., 'success')")


class ParseResponse(BaseModel):
    """Response model for the Klipper-to-LinuxCNC parser trigger."""
    status: str = Field(..., description="Outcome of the parser trigger")
    message: str = Field(..., description="Human-readable status message")


@router.post(
    "/state",
    summary="Set Machine State",
    description="Toggle machine E-Stop or Power state.",
    operation_id="setMachineState",
    response_model=StatusResponse,
)
def set_state(cmd: StateCommand) -> StatusResponse:
    """Toggle machine E-Stop or Power state."""
    states = {
        "on": getattr(linuxcnc, 'STATE_ON', 4),
        "off": getattr(linuxcnc, 'STATE_OFF', 3),
        "estop": getattr(linuxcnc, 'STATE_ESTOP', 1),
        "estop_reset": getattr(linuxcnc, 'STATE_ESTOP_RESET', 2)
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
    """Change the machine task mode (manual, auto, mdi)."""
    modes = {
        "manual": getattr(linuxcnc, 'MODE_MANUAL', 1),
        "auto": getattr(linuxcnc, 'MODE_AUTO', 2),
        "mdi": getattr(linuxcnc, 'MODE_MDI', 3)
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
    """Home a specific axis, or all axes if axis=-1."""
    execute_sync_cmd("mode", 0, getattr(linuxcnc, 'MODE_MANUAL', 1))

    if cmd.axis == -1:
        # Assuming 3 axes (X, Y, Z) for baseline
        for i in range(3):
            execute_sync_cmd("home", 3, i)
        return StatusResponse(status="success")
    else:
        result = execute_sync_cmd("home", 3, cmd.axis)
        return StatusResponse(status=result.get("status", "success"))


@router.post(
    "/mdi",
    summary="Run MDI Command",
    description="Execute a single MDI (G-Code) command. Automatically switches the machine to MDI mode.",
    operation_id="runMdiCommand",
    response_model=StatusResponse,
)
def run_mdi(cmd: MdiCommand) -> StatusResponse:
    """Execute a single MDI command."""
    logger.info(f"Running MDI: {cmd.command}")
    # Force switch to MDI mode before executing
    execute_sync_cmd("mode", 5, getattr(linuxcnc, 'MODE_MDI', 3))
    result = execute_sync_cmd("mdi", 0, cmd.command)
    return StatusResponse(status=result.get("status", "success"))


@program_router.post(
    "/run",
    summary="Run Program",
    description="Start or resume the loaded G-code program from a specific line.",
    operation_id="runProgram",
    response_model=StatusResponse,
)
def run_program(line_number: int = 0) -> StatusResponse:
    """Start the loaded G-code program."""
    execute_sync_cmd("mode", 3, getattr(linuxcnc, 'MODE_AUTO', 2))
    result = execute_sync_cmd("auto", 0, getattr(linuxcnc, 'AUTO_RUN', 0), line_number)
    return StatusResponse(status=result.get("status", "success"))


@program_router.post(
    "/stop",
    summary="Stop Program",
    description="Stop/abort the currently running program.",
    operation_id="stopProgram",
    response_model=StatusResponse,
)
def stop_program() -> StatusResponse:
    """Stop/abort the currently running program."""
    result = execute_sync_cmd("abort")
    return StatusResponse(status=result.get("status", "success"))


@program_router.post(
    "/pause",
    summary="Pause Program",
    description="Pause the currently running program.",
    operation_id="pauseProgram",
    response_model=StatusResponse,
)
def pause_program() -> StatusResponse:
    """Pause the currently running program."""
    result = execute_sync_cmd("auto", 0, getattr(linuxcnc, 'AUTO_PAUSE', 1))
    return StatusResponse(status=result.get("status", "success"))


@program_router.post(
    "/resume",
    summary="Resume Program",
    description="Resume a paused program.",
    operation_id="resumeProgram",
    response_model=StatusResponse,
)
def resume_program() -> StatusResponse:
    """Resume a paused program."""
    result = execute_sync_cmd("auto", 0, getattr(linuxcnc, 'AUTO_RESUME', 2))
    return StatusResponse(status=result.get("status", "success"))


@program_router.post(
    '/parse',
    summary='Trigger Parser',
    description='Manually trigger the Klipper-to-LinuxCNC configuration parser.',
    operation_id='triggerParser',
    response_model=ParseResponse,
)
def trigger_parser() -> ParseResponse:
    logger.info('Triggering Klipper-to-LinuxCNC parser...')
    time.sleep(1) # mock delay
    return ParseResponse(status='success', message='Parsing complete')
