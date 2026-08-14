"""HTTP router for jog endpoints of the machine module.

This module owns the three jog endpoints and the module-private
``_active_jogs`` dictionary that backs the keep-alive watchdog. The
watchdog itself lives in :mod:`backend.modules.axis.jog_watchdog`
so it can be started and stopped independently from the router.

Endpoints (REST, **deprecated** — see ``servo_thread.py`` for the
canonical WebSocket path)
-----------------

* ``POST /jog`` — start, step, or stop a jog.
* ``POST /jog/keepalive`` — refresh the watchdog timer.
* ``POST /jog/stop`` — explicitly stop a continuous jog.

The REST endpoints stay as a backward-compat fallback for
non-WebSocket clients. The frontend now uses the
``/ws/telemetry`` channel for all three messages; the WS path
dispatches to the same ``ws_*`` helpers below so behaviour is
identical and a single source of truth backs both transports.

Safety contract
---------------

The 500 ms keep-alive watchdog (see ``jog_watchdog.py``) is the
single source of truth for "is this axis currently jogging under
the user's control". If the frontend stops pinging, the watchdog
force-stops the axis within ``jog_watchdog_timeout_ms`` (read from
the module settings at boot). This invariant **must not** regress —
tests in ``tests/test_jog_watchdog.py`` cover the behaviour.
"""
from __future__ import annotations

import logging
import threading
import time
import warnings
from typing import Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hardware import execute_sync_cmd, linuxcnc

logger = logging.getLogger("backend.modules.axis.jog")


# ---------------------------------------------------------------------- #
# Module-private watchdog state                                           #
# ---------------------------------------------------------------------- #

# ``_active_jogs`` is module-private state shared between this router
# and ``jog_watchdog.py``. Both modules import from this ``jog`` module
# so the state lives in exactly one place; the watchdog reads it
# under :data:`_active_jogs_lock`.
#
# Keyed by axis index (``0`` = X, ``1`` = Y, ``2`` = Z). Value is the
# ``time.time()`` timestamp of the last keep-alive ping. The watchdog
# force-stops any axis whose stamp is older than ``WATCHDOG_TIMEOUT_S``.
_active_jogs: Dict[int, float] = {}
_active_jogs_lock = threading.Lock()
# Compatibility aliases for code that imported the old router-level names.
active_jogs = _active_jogs
active_jogs_lock = _active_jogs_lock


def _stop_axis(axis: int) -> None:
    s = linuxcnc.stat()
    s.poll()
    is_teleop = (s.motion_mode == getattr(linuxcnc, "TRAJ_MODE_TELEOP", 3))

    if hasattr(s, 'joints') and hasattr(s, 'homed') and s.joints > 0:
        if all(s.homed[:s.joints]):
            is_teleop = True

    execute_sync_cmd("jog", 0, getattr(linuxcnc, "JOG_STOP", 0), is_teleop, axis)


def clear_active_jogs() -> None:
    """Drop every entry in :data:`_active_jogs`.

    Called by :func:`jog_watchdog.stop_watchdog` so a reload never
    resumes a stale jog whose keep-alive trail was lost when the
    asyncio task was torn down.
    """
    with _active_jogs_lock:
        _active_jogs.clear()


def snapshot_active_jogs() -> List[int]:
    """Return a snapshot of the axes currently considered active.

    Test-only helper; the watchdog reads the dict in-process so it
    does not need this — but the test-suite does.
    """
    with _active_jogs_lock:
        return list(_active_jogs.keys())


# ---------------------------------------------------------------------- #
# Pydantic request / response models                                      #
# ---------------------------------------------------------------------- #


class JogCommand(BaseModel):
    """Pydantic model for executing a jog."""

    velocities: Dict[int, float] = Field(
        ...,
        description=(
            "Mapping of axis index (0=X, 1=Y, 2=Z) to signed jog "
            "velocity in user units per minute"
        ),
    )
    distance: float = Field(
        default=0.0,
        description=(
            "Absolute step distance in mm; non-zero enables an "
            "incremental jog instead of continuous"
        ),
    )


class JogStopCommand(BaseModel):
    """Pydantic model for stopping a jog or sending a keep-alive ping."""

    axes: List[int] = Field(
        ...,
        description="Axis indices affected by this stop / keepalive call",
    )


class JogResponse(BaseModel):
    """Response model for a jog command."""

    status: str = Field(..., description="Outcome summary (e.g., 'ok')")
    results: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Per-axis hardware layer results keyed by axis index (as "
            "string for JSON friendliness)"
        ),
    )


class JogStatusResponse(BaseModel):
    """Response model for keepalive / stop jog endpoints."""

    status: str = Field(..., description="Outcome summary (e.g., 'ok')")


# ---------------------------------------------------------------------- #
# WebSocket-shared helpers                                                  #
# ---------------------------------------------------------------------- #


def ws_jog_keepalive(axes: List[int]) -> None:
    """Refresh the watchdog timer for ``axes``.

    Public so ``backend/routers/servo_thread.py`` can dispatch the
    ``{"type": "jog_keepalive", "axes": [...]}`` inbound message
    to the same watchdog update the REST endpoint performs. Axes
    that are not currently registered as active are ignored — the
    watchdog only cares about continuous jogs that have started.
    """
    with _active_jogs_lock:
        for axis in axes:
            if axis in _active_jogs:
                _active_jogs[axis] = time.time()


def ws_jog_axis(velocities: Dict[int, float], distance: float) -> None:
    """Issue a jog command. Shared by ``POST /jog`` and the WS path.

    Continuous-vs-step is decided by ``distance``: non-zero enables
    an incremental jog (``JOG_INCREMENT``) and registers the axis
    with the watchdog as a one-shot, so a missed keep-alive does not
    halt the axis mid-step. Continuous (``distance=0``) registers
    the axis with the watchdog as a sustained jog.
    """
    execute_sync_cmd(
        "mode", 0, getattr(linuxcnc, "MODE_MANUAL", 1)
    )

    s = linuxcnc.stat()
    s.poll()
    is_teleop = (s.motion_mode == getattr(linuxcnc, "TRAJ_MODE_TELEOP", 3))

    if hasattr(s, 'joints') and hasattr(s, 'homed') and s.joints > 0:
        if all(s.homed[:s.joints]):
            if not is_teleop:
                logger.info("Self-healing: Machine fully homed but in Free mode. Forcing Teleop.")
                execute_sync_cmd("teleop_enable", 0, 1)
            is_teleop = True
    teleop_flag = 1 if is_teleop else 0

    for axis, velocity in velocities.items():
        if velocity == 0:
            continue

        if distance != 0:
            execute_sync_cmd(
                "jog",
                0,
                getattr(linuxcnc, "JOG_INCREMENT", 2),
                teleop_flag,
                axis,
                velocity,
                distance,
            )
        else:
            with _active_jogs_lock:
                _active_jogs[axis] = time.time()
            execute_sync_cmd(
                "jog",
                0,
                getattr(linuxcnc, "JOG_CONTINUOUS", 1),
                teleop_flag,
                axis,
                velocity,
            )


def ws_jog_stop(axes: List[int]) -> None:
    """Stop the continuous jog registered on ``axes``.

    Public so ``backend/routers/servo_thread.py`` can dispatch the
    ``{"type": "jog_stop", "axes": [...]}`` inbound message to the
    same watchdog-cleanup path the REST endpoint performs.
    """
    with _active_jogs_lock:
        for axis in axes:
            _active_jogs.pop(axis, None)

    for axis in axes:
        _stop_axis(axis)


__all__ = [
    # Public so ``backend/routers/servo_thread.py`` can dispatch
    # inbound JSON messages to the same watchdog / dispatch
    # logic. Single source of truth for the three jog actions.
    #
    # ``router`` is intentionally absent — the FastAPI router for
    # the jog endpoints now lives in ``modules/machine/router.py``'s
    # merged router (see ``module.py::AxisModule.__init__``),
    # which keeps the jog watchdog helpers (``_active_jogs``,
    # ``ws_jog_*``) in the same package as the watchdog itself
    # (in ``jog_watchdog.py``). Importing ``router`` from this
    # module was a stale pattern that broke after the consolidation.
    "ws_jog_axis",
    "ws_jog_stop",
    "_active_jogs",
    "_active_jogs_lock",
    "active_jogs",
    "active_jogs_lock",
    "clear_active_jogs",
    "snapshot_active_jogs",
]
