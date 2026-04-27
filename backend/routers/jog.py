import time
import threading
import asyncio
import logging
from fastapi import APIRouter
from pydantic import BaseModel
from hardware import execute_sync_cmd, linuxcnc

logger = logging.getLogger("backend.routers.jog")
router = APIRouter(prefix="/api/v1/machine", tags=["jog"])

# Track active continuous jogs and last-ping timestamps
active_jogs = {}
active_jogs_lock = threading.Lock()


class JogCommand(BaseModel):
    """Pydantic model for executing a jog."""
    axis: int
    velocity: float
    distance: float = 0.0


class JogStopCommand(BaseModel):
    """Pydantic model for stopping a jog or sending a keep-alive ping."""
    axis: int


async def jog_watchdog():
    """
    Background watchdog task that monitors continuous jogs.
    If a keep-alive ping is not received within 500ms, it automatically
    halts the axis to prevent a runaway machine crash.
    """
    while True:
        await asyncio.sleep(0.1)
        now = time.time()
        with active_jogs_lock:
            # Find axes that haven't been pinged in 500ms
            expired_axes = [axis for axis, t in active_jogs.items() if now - t > 0.5]
            for axis in expired_axes:
                logger.warning(f"SAFETY WATCHDOG: Missed keep-alive for Axis {axis}. Executing STOP!")
                del active_jogs[axis]
                execute_sync_cmd("jog", 0, getattr(linuxcnc, 'JOG_STOP', 0), True, axis)


@router.post("/jog")
def jog_axis(cmd: JogCommand):
    """
    Initiates a jog. Supports step, continuous, or stop commands
    depending on the velocity and distance parameters.
    """
    execute_sync_cmd("mode", 0, getattr(linuxcnc, 'MODE_MANUAL', 1))
    
    if cmd.velocity == 0:
        return execute_sync_cmd("jog", 0, getattr(linuxcnc, 'JOG_STOP', 0), True, cmd.axis)
    elif cmd.distance != 0:
        return execute_sync_cmd("jog", 0, getattr(linuxcnc, 'JOG_INCREMENT', 2), True, cmd.axis, cmd.velocity, cmd.distance)
    else:
        # Register the start of a continuous jog for the watchdog
        with active_jogs_lock:
            active_jogs[cmd.axis] = time.time()
        return execute_sync_cmd("jog", 0, getattr(linuxcnc, 'JOG_CONTINUOUS', 1), True, cmd.axis, cmd.velocity)


@router.post("/jog/keepalive")
def jog_keepalive(cmd: JogStopCommand):
    """
    Refreshes the watchdog timer for an actively jogging axis.
    Must be called frequently (e.g., every 250ms) during continuous jogging.
    """
    with active_jogs_lock:
        if cmd.axis in active_jogs:
            active_jogs[cmd.axis] = time.time()
    return {"status": "ok"}


@router.post("/jog/stop")
def stop_jog(cmd: JogStopCommand):
    """
    Explicitly stops a continuous jog and removes it from the watchdog.
    """
    execute_sync_cmd("mode", 0, getattr(linuxcnc, 'MODE_MANUAL', 1))
    with active_jogs_lock:
        active_jogs.pop(cmd.axis, None)
    return execute_sync_cmd("jog", 0, getattr(linuxcnc, 'JOG_STOP', 0), True, cmd.axis)