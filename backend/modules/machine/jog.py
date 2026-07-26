"""HTTP router for jog endpoints of the machine module.

This module owns the three jog endpoints and the module-private
``_active_jogs`` dictionary that backs the keep-alive watchdog. The
watchdog itself lives in :mod:`backend.modules.machine.jog_watchdog`
so it can be started and stopped independently from the router.

Endpoints
---------

* ``POST /jog`` — start, step, or stop a jog.
* ``POST /jog/keepalive`` — refresh the watchdog timer (called by
  the frontend every ~250 ms during a continuous jog).
* ``POST /jog/stop`` — explicitly stop a continuous jog.

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
from typing import Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hardware import execute_sync_cmd, linuxcnc

logger = logging.getLogger("backend.modules.machine.jog")


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
    """Force-stop ``axis`` via the hardware layer.

    Public-ish so the watchdog can call it without re-importing
    ``execute_sync_cmd``.
    """
    execute_sync_cmd("jog", 0, getattr(linuxcnc, "JOG_STOP", 0), True, axis)


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
# Endpoints                                                              #
# ---------------------------------------------------------------------- #


# The router is module-level so the registry can mount it under
# ``/api/v1/modules/machine``. The endpoints take no ``prefix``
# because the registry supplies it.
router = APIRouter(tags=["modules:machine"])


@router.post(
    "/jog",
    summary="Jog Axis",
    description=(
        "Initiates a jog. Supports step, continuous, or stop commands "
        "depending on the velocity and distance parameters. A "
        "continuous jog (distance=0) registers the axis with the "
        "500 ms keep-alive watchdog; the watchdog force-stops the "
        "axis if no keep-alive ping arrives within the configured "
        "timeout."
    ),
    operation_id="jogAxis",
    response_model=JogResponse,
)
def jog_axis(cmd: JogCommand) -> JogResponse:
    """Initiate a jog.

    Continuous-vs-step is decided by ``cmd.distance``: non-zero enables
    an incremental jog (``JOG_INCREMENT``) and registers the axis with
    the watchdog as a one-shot, so a missed keep-alive does not halt
    the axis mid-step. Continuous (distance=0) registers the axis
    with the watchdog as a sustained jog.
    """
    execute_sync_cmd(
        "mode", 0, getattr(linuxcnc, "MODE_MANUAL", 1)
    )

    results: Dict[str, str] = {}
    for axis, velocity in cmd.velocities.items():
        if velocity == 0:
            continue

        if cmd.distance != 0:
            result = execute_sync_cmd(
                "jog",
                0,
                getattr(linuxcnc, "JOG_INCREMENT", 2),
                True,
                axis,
                velocity,
                cmd.distance,
            )
        else:
            # Continuous — register with the watchdog so a missed
            # keep-alive force-stops the axis.
            with _active_jogs_lock:
                _active_jogs[axis] = time.time()
            result = execute_sync_cmd(
                "jog",
                0,
                getattr(linuxcnc, "JOG_CONTINUOUS", 1),
                True,
                axis,
                velocity,
            )
        results[str(axis)] = result.get("status", "success")

    return JogResponse(status="ok", results=results)


@router.post(
    "/jog/keepalive",
    summary="Jog Keep-Alive",
    description=(
        "Refreshes the watchdog timer for an actively jogging axis. "
        "Must be called frequently (e.g., every 250 ms) during a "
        "continuous jog."
    ),
    operation_id="jogKeepalive",
    response_model=JogStatusResponse,
)
def jog_keepalive(cmd: JogStopCommand) -> JogStatusResponse:
    """Refresh the watchdog timer for ``cmd.axes``.

    Axes that are not currently registered as active are ignored — the
    watchdog only cares about continuous jogs that have started.
    """
    with _active_jogs_lock:
        for axis in cmd.axes:
            if axis in _active_jogs:
                _active_jogs[axis] = time.time()
    return JogStatusResponse(status="ok")


@router.post(
    "/jog/stop",
    summary="Stop Jogging",
    description=(
        "Explicitly stops a continuous jog and removes it from the "
        "watchdog. Idempotent: stopping an axis that is not "
        "currently active is a no-op."
    ),
    operation_id="jogStop",
    response_model=JogStatusResponse,
)
def stop_jog(cmd: JogStopCommand) -> JogStatusResponse:
    """Stop the continuous jog registered on ``cmd.axes``."""
    with _active_jogs_lock:
        for axis in cmd.axes:
            _active_jogs.pop(axis, None)

    for axis in cmd.axes:
        _stop_axis(axis)

    return JogStatusResponse(status="ok")


__all__ = [
    "router",
    "jog_axis",
    "jog_keepalive",
    "stop_jog",
    "_active_jogs",
    "_active_jogs_lock",
    "active_jogs",
    "active_jogs_lock",
    "clear_active_jogs",
    "snapshot_active_jogs",
]
