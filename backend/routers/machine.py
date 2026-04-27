import os
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from hardware import execute_sync_cmd, linuxcnc

logger = logging.getLogger("backend.routers.machine")

router = APIRouter(prefix="/api/v1/machine", tags=["machine"])
program_router = APIRouter(prefix="/api/v1/program", tags=["program"])
file_router = APIRouter(prefix="/api/v1/file", tags=["file"])


class StateCommand(BaseModel):
    """Pydantic model for setting machine power state."""
    state: str  # 'on', 'off', 'estop', 'estop_reset'


class ModeCommand(BaseModel):
    """Pydantic model for setting machine task mode."""
    mode: str  # 'manual', 'mdi', 'auto'


class HomeCommand(BaseModel):
    """Pydantic model for homing an axis."""
    axis: int


class MdiCommand(BaseModel):
    """Pydantic model for executing MDI commands."""
    command: str


class GcodeFile(BaseModel):
    """Pydantic model for uploading/loading a G-code file."""
    name: str
    content: str


@router.post("/state")
def set_state(cmd: StateCommand):
    """Toggle machine E-Stop or Power state."""
    states = {
        "on": getattr(linuxcnc, 'STATE_ON', 4),
        "off": getattr(linuxcnc, 'STATE_OFF', 3),
        "estop": getattr(linuxcnc, 'STATE_ESTOP', 1),
        "estop_reset": getattr(linuxcnc, 'STATE_ESTOP_RESET', 2)
    }
    if cmd.state not in states:
        raise HTTPException(status_code=400, detail="Invalid state")
    return execute_sync_cmd("state", 3, states[cmd.state])


@router.post("/mode")
def set_mode(cmd: ModeCommand):
    """Change the machine task mode (manual, auto, mdi)."""
    modes = {
        "manual": getattr(linuxcnc, 'MODE_MANUAL', 1),
        "auto": getattr(linuxcnc, 'MODE_AUTO', 2),
        "mdi": getattr(linuxcnc, 'MODE_MDI', 3)
    }
    if cmd.mode not in modes:
        raise HTTPException(status_code=400, detail="Invalid mode")
    return execute_sync_cmd("mode", 5, modes[cmd.mode])


@router.post("/home")
def home_axis(cmd: HomeCommand):
    """Home a specific axis, or all axes if axis=-1."""
    execute_sync_cmd("mode", 0, getattr(linuxcnc, 'MODE_MANUAL', 1))
    
    if cmd.axis == -1:
        # Assuming 3 axes (X, Y, Z) for baseline
        for i in range(3):
            execute_sync_cmd("home", 3, i)
        return {"status": "success"}
    else:
        return execute_sync_cmd("home", 3, cmd.axis)


@router.post("/mdi")
def run_mdi(cmd: MdiCommand):
    """Execute a single MDI command."""
    logger.info(f"Running MDI: {cmd.command}")
    return execute_sync_cmd("mdi", 0, cmd.command)


@program_router.post("/run")
def run_program(line_number: int = 0):
    """Start the loaded G-code program."""
    execute_sync_cmd("mode", 3, getattr(linuxcnc, 'MODE_AUTO', 2))
    return execute_sync_cmd("auto", 0, getattr(linuxcnc, 'AUTO_RUN', 0), line_number)


@program_router.post("/stop")
def stop_program():
    """Stop/abort the currently running program."""
    return execute_sync_cmd("abort")


@program_router.post("/pause")
def pause_program():
    """Pause the currently running program."""
    return execute_sync_cmd("auto", 0, getattr(linuxcnc, 'AUTO_PAUSE', 1))


@program_router.post("/resume")
def resume_program():
    """Resume a paused program."""
    return execute_sync_cmd("auto", 0, getattr(linuxcnc, 'AUTO_RESUME', 2))


@file_router.post("/load")
def load_gcode(file: GcodeFile):
    """Load a G-code file onto the CNC controller."""
    path = os.path.join("/tmp", file.name)
    try:
        with open(path, 'w') as f:
            f.write(file.content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write file: {e}")

    execute_sync_cmd("reset_interpreter")
    execute_sync_cmd("mode", 3, getattr(linuxcnc, 'MODE_AUTO', 2))
    res = execute_sync_cmd("program_open", 5, path)
    execute_sync_cmd("mode", 3, getattr(linuxcnc, 'MODE_MANUAL', 1))
    return res