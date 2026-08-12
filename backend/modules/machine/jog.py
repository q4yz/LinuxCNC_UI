"""HTTP router for jog endpoints of the machine module.

This module owns the three jog endpoints and the module-private
``_active_jogs`` dictionary that backs the keep-alive watchdog. The
watchdog itself lives in :mod:`backend.modules.machine.jog_watchdog`
so it can be started and stopped independently from the router.

Endpoints (REST, **deprecated** — see ``websocket.py`` for the
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
# WebSocket-shared helpers                                                  #
# ---------------------------------------------------------------------- #


def ws_jog_keepalive(axes: List[int]) -> None:
    """Refresh the watchdog timer for ``axes``.

    Public so ``backend/routers/websocket.py`` can dispatch the
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

    for axis, velocity in velocities.items():
        if velocity == 0:
            continue

        if distance != 0:
            execute_sync_cmd(
                "jog",
                0,
                getattr(linuxcnc, "JOG_INCREMENT", 2),
                True,
                axis,
                velocity,
                distance,
            )
        else:
            # Continuous — register with the watchdog so a missed
            # keep-alive force-stops the axis.
            with _active_jogs_lock:
                _active_jogs[axis] = time.time()
            execute_sync_cmd(
                "jog",
                0,
                getattr(linuxcnc, "JOG_CONTINUOUS", 1),
                True,
                axis,
                velocity,
            )


def ws_jog_stop(axes: List[int]) -> None:
    """Stop the continuous jog registered on ``axes``.

    Public so ``backend/routers/websocket.py`` can dispatch the
    ``{"type": "jog_stop", "axes": [...]}`` inbound message to the
    same watchdog-cleanup path the REST endpoint performs.
    """
    with _active_jogs_lock:
        for axis in axes:
            _active_jogs.pop(axis, None)

    for axis in axes:
        _stop_axis(axis)


# ---------------------------------------------------------------------- #
# Endpoints                                                              #
# ---------------------------------------------------------------------- #


# The router is module-level so the registry can mount it under
# ``/api/v1/modules/machine``. The endpoints take no ``prefix``
# because the registry supplies it.
router = APIRouter()


@router.post(
    "/jog",
    summary="Jog Axis",
    description=(
        "**Deprecated** — prefer the ``/ws/telemetry`` socket with "
        "a JSON message of type ``jog_axis`` and the same payload. "
        "The REST endpoint will be removed in the next major "
        "release.\n\n"
        "Initiates a jog. Supports step, continuous, or stop "
        "commands depending on the velocity and distance parameters. "
        "A continuous jog (distance=0) registers the axis with the "
        "500 ms keep-alive watchdog; the watchdog force-stops the "
        "axis if no keep-alive ping arrives within the configured "
        "timeout."
    ),
    operation_id="jogAxis",
    response_model=JogResponse,
    deprecated=True,
)
def jog_axis(cmd: JogCommand) -> JogResponse:
    """Initiate a jog.

    **Deprecated** — see ``ws_jog_axis`` for the canonical entry
    point shared with the WebSocket transport. The REST endpoint
    is kept as a backward-compat fallback; new code should send a
    ``jog_axis`` JSON message over the ``/ws/telemetry`` socket
    instead.
    """
    warnings.warn(
        "POST /api/v1/modules/machine/jog is deprecated; "
        "send {type: 'jog_axis', ...} over /ws/telemetry instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    ws_jog_axis(cmd.velocities, cmd.distance)
    results: Dict[str, str] = {
        str(axis): "success" for axis in cmd.velocities.keys() if cmd.velocities[axis] != 0
    }
    return JogResponse(status="ok", results=results)


@router.post(
    "/jog/keepalive",
    summary="Jog Keep-Alive",
    description=(
        "**Deprecated** — prefer the ``/ws/telemetry`` socket with "
        "a JSON message of type ``jog_keepalive`` and the same "
        "payload. The REST endpoint will be removed in the next "
        "major release.\n\n"
        "Refreshes the watchdog timer for an actively jogging axis. "
        "Must be called frequently (e.g., every 250 ms) during a "
        "continuous jog."
    ),
    operation_id="jogKeepalive",
    response_model=JogStatusResponse,
    deprecated=True,
)
def jog_keepalive(cmd: JogStopCommand) -> JogStatusResponse:
    """Refresh the watchdog timer for ``cmd.axes``.

    **Deprecated** — see ``ws_jog_keepalive`` for the canonical
    entry point shared with the WebSocket transport.
    """
    warnings.warn(
        "POST /api/v1/modules/machine/jog/keepalive is deprecated; "
        "send {type: 'jog_keepalive', ...} over /ws/telemetry instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    ws_jog_keepalive(list(cmd.axes))
    return JogStatusResponse(status="ok")


@router.post(
    "/jog/stop",
    summary="Stop Jogging",
    description=(
        "**Deprecated** — prefer the ``/ws/telemetry`` socket with "
        "a JSON message of type ``jog_stop`` and the same payload. "
        "The REST endpoint will be removed in the next major "
        "release.\n\n"
        "Explicitly stops a continuous jog and removes it from the "
        "watchdog. Idempotent: stopping an axis that is not "
        "currently active is a no-op."
    ),
    operation_id="jogStop",
    response_model=JogStatusResponse,
    deprecated=True,
)
def stop_jog(cmd: JogStopCommand) -> JogStatusResponse:
    """Stop the continuous jog registered on ``cmd.axes``.

    **Deprecated** — see ``ws_jog_stop`` for the canonical entry
    point shared with the WebSocket transport.
    """
    warnings.warn(
        "POST /api/v1/modules/machine/jog/stop is deprecated; "
        "send {type: 'jog_stop', ...} over /ws/telemetry instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    ws_jog_stop(list(cmd.axes))
    return JogStatusResponse(status="ok")


__all__ = [
    "router",
    "jog_axis",
    "jog_keepalive",
    "stop_jog",
    # Public so ``backend/routers/websocket.py`` can dispatch
    # inbound JSON messages to the same watchdog / dispatch
    # logic. Single source of truth for the three jog actions.
    "ws_jog_axis",
    "ws_jog_keepalive",
    "ws_jog_stop",
    "_active_jogs",
    "_active_jogs_lock",
    "active_jogs",
    "active_jogs_lock",
    "clear_active_jogs",
    "snapshot_active_jogs",
]
