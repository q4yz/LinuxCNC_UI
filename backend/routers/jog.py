import time
import threading
import asyncio
import logging
from typing import Dict, List
from fastapi import APIRouter
from pydantic import BaseModel
from hardware import execute_sync_cmd, linuxcnc

logger = logging.getLogger("backend.routers.jog")
router = APIRouter(prefix="/api/v1/machine", tags=["Jogging"])

# Track active continuous jogs and last-ping timestamps
active_jogs = {}
active_jogs_lock = threading.Lock()


class JogCommand(BaseModel):
    """Pydantic model for executing a jog."""
    velocities: Dict[int, float]
    distance: float = 0.0


class JogStopCommand(BaseModel):
    """Pydantic model for stopping a jog or sending a keep-alive ping."""
    axes: List[int]


def _stop_axis(axis: int) -> None:
    execute_sync_cmd("jog", 0, getattr(linuxcnc, 'JOG_STOP', 0), True, axis)


async def jog_watchdog():
    """
    Background watchdog task that monitors continuous jogs.
    If a keep-alive ping is not received within 500ms, it automatically
    halts the axis to prevent a runaway machine crash.
    """
    while True:
        await asyncio.sleep(0.1)
        now = time.time()
        expired_axes = []
        with active_jogs_lock:
            # Find axes that haven't been pinged in 500ms
            expired_axes = [axis for axis, t in active_jogs.items() if now - t > 0.5]
            for axis in expired_axes:
                logger.warning(f"SAFETY WATCHDOG: Missed keep-alive for Axis {axis}. Executing STOP!")
                del active_jogs[axis]
        for axis in expired_axes:
            _stop_axis(axis)


@router.post("/jog", summary="Jog Axis", description="Initiates a jog. Supports step, continuous, or stop commands depending on parameters.")
def jog_axis(cmd: JogCommand):
    """
    Initiates a jog. Supports step, continuous, or stop commands
    depending on the velocity and distance parameters.
    """
    execute_sync_cmd("mode", 0, getattr(linuxcnc, 'MODE_MANUAL', 1))

    results = {}
    for axis, velocity in cmd.velocities.items():
        if velocity == 0:
            continue

        if cmd.distance != 0:
            results[axis] = execute_sync_cmd(
                "jog",
                0,
                getattr(linuxcnc, 'JOG_INCREMENT', 2),
                True,
                axis,
                velocity,
                cmd.distance,
            )
        else:
            with active_jogs_lock:
                active_jogs[axis] = time.time()
            results[axis] = execute_sync_cmd(
                "jog",
                0,
                getattr(linuxcnc, 'JOG_CONTINUOUS', 1),
                True,
                axis,
                velocity,
            )

    return {"status": "ok", "results": results}


@router.post("/jog/keepalive", summary="Jog Keep-Alive", description="Refreshes the watchdog timer for an actively jogging axis. Must be called frequently.")
def jog_keepalive(cmd: JogStopCommand):
    """
    Refreshes the watchdog timer for an actively jogging axis.
    Must be called frequently (e.g., every 250ms) during continuous jogging.
    """
    with active_jogs_lock:
        for axis in cmd.axes:
            if axis in active_jogs:
                active_jogs[axis] = time.time()
    return {"status": "ok"}


@router.post("/jog/stop", summary="Stop Jogging", description="Explicitly stops a continuous jog and removes it from the watchdog.")
def stop_jog(cmd: JogStopCommand):
    """
    Explicitly stops a continuous jog and removes it from the watchdog.
    """
    with active_jogs_lock:
        for axis in cmd.axes:
            active_jogs.pop(axis, None)

    for axis in cmd.axes:
        _stop_axis(axis)

    return {"status": "ok"}