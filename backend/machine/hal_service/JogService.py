"""Jog hardware service.

Owns every call into the LinuxCNC NML command channel for jog
control, plus the watchdog's active-jog map (``_active_jogs``).
The 500 ms keep-alive watchdog in
:mod:`axis.jog_watchdog` is pure logic — it has
no ``from hardware import …`` — and calls into this service for
state reads (``snapshot_active_jogs``) and the hardware-stop
dispatch (``stop_axis``).

Public functions used by the WebSocket dispatcher in
:mod:`backend.routers.servo_thread` (and the deprecated REST
handlers, kept as a back-compat fallback):

* :func:`jog_axis` — issue a jog command, continuous or step.
* :func:`jog_stop` — stop continuous jogs on the listed axes.
* :func:`jog_keepalive` — refresh the watchdog timer.
* :func:`stop_axis` — force-stop a single axis (used by both
  :func:`jog_stop` and the watchdog).

State helpers used by the watchdog and tests:

* :func:`snapshot_active_jogs` — copy of ``_active_jogs``.
* :func:`clear_active_jogs` — drop every entry.

The dead Pydantic request / response models from the deprecated
REST endpoints (``JogCommand`` / ``JogStopCommand`` /
``JogResponse`` / ``JogStatusResponse``) were removed in this
refactor; ``grep`` confirms zero references anywhere else.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List

from hardware import execute_sync_cmd, linuxcnc

logger = logging.getLogger("backend.axis_service")


# ────────────────────────────────────────────────────────────────────── #
# Module-private watchdog state                                            #
# ────────────────────────────────────────────────────────────────────── #

# ``_active_jogs`` is keyed by axis index (``0`` = X, ``1`` = Y,
# ``2`` = Z). Value is the ``time.time()`` timestamp of the last
# keep-alive ping. The watchdog force-stops any axis whose stamp is
# older than ``WATCHDOG_TIMEOUT_S``. Both ``jog_axis`` (which writes)
# and the watchdog (which reads + clears stale entries) acquire
# ``_active_jogs_lock`` to keep the map consistent across threads.
_active_jogs: Dict[int, float] = {}
_active_jogs_lock = threading.Lock()


def _register_active_jog(axis: int) -> None:
    """Stamp ``axis`` as actively jogging.

    Internal — used by :func:`jog_axis` when the jog is continuous
    (``distance == 0``). Step jogs (``distance != 0``) are one-shot
    and not registered.
    """
    with _active_jogs_lock:
        _active_jogs[axis] = time.time()


def _unregister_active_jog(axis: int) -> None:
    """Drop ``axis`` from the active set.

    Internal — used by :func:`jog_stop` and by the watchdog after it
    has called :func:`stop_axis` on an expired entry.
    """
    with _active_jogs_lock:
        _active_jogs.pop(axis, None)


def snapshot_active_jogs() -> Dict[int, float]:
    """Return a copy of the active-jog map (axis → last-ping timestamp).

    Used by the watchdog to find expired axes. Returns a copy under
    the lock so the caller can iterate without holding it.
    """
    with _active_jogs_lock:
        return dict(_active_jogs)


def clear_active_jogs() -> None:
    """Drop every entry in :data:`_active_jogs`.

    Called by :func:`axis.jog_watchdog.stop_watchdog`
    so a reload never resumes a stale jog whose keep-alive trail
    was lost when the asyncio task was torn down.
    """
    with _active_jogs_lock:
        _active_jogs.clear()


# ────────────────────────────────────────────────────────────────────── #
# Hardware dispatch                                                        #
# ────────────────────────────────────────────────────────────────────── #


def stop_axis(axis: int) -> None:
    """Force-stop a single axis via the NML command channel."""
    s = linuxcnc.stat()
    # NML Shared Memory Flush: double-poll with a tiny delay for
    # fresh data. Same pattern the legacy router used.
    for _ in range(2):
        s.poll()
        time.sleep(0.01)

    is_teleop = (
        s.motion_mode == getattr(linuxcnc, "TRAJ_MODE_TELEOP", 3)
    )

    # ``joint=1`` when in FREE/JOINT mode (per-joint jogging);
    # ``joint=0`` when in TELEOP mode (Cartesian jogging).
    joint_flag = 0 if is_teleop else 1
    execute_sync_cmd(
        "jog", 0, getattr(linuxcnc, "JOG_STOP", 0), joint_flag, axis
    )


def jog_axis(velocities: Dict[int, float], distance: float) -> None:
    """Issue a jog command. Continuous-vs-step is decided by ``distance``."""
    execute_sync_cmd("mode", 0.1, getattr(linuxcnc, "MODE_MANUAL", 1))

    s = linuxcnc.stat()
    # NML Shared Memory Flush: triple-poll forces Python to pull the
    # freshest status data from LinuxCNC after the mode switch.
    for _ in range(3):
        s.poll()
        time.sleep(0.01)

    is_teleop = (
        s.motion_mode == getattr(linuxcnc, "TRAJ_MODE_TELEOP", 3)
    )

    joint_flag = 0 if is_teleop else 1

    for axis, velocity in velocities.items():
        if velocity == 0:
            continue

        if distance != 0:
            execute_sync_cmd(
                "jog",
                0,
                getattr(linuxcnc, "JOG_INCREMENT", 2),
                joint_flag,
                axis,
                velocity,
                distance,
            )
        else:
            _register_active_jog(axis)
            execute_sync_cmd(
                "jog",
                0,
                getattr(linuxcnc, "JOG_CONTINUOUS", 1),
                joint_flag,
                axis,
                velocity,
            )


def jog_stop(axes: List[int]) -> None:
    """Stop continuous jogs on the listed axes."""
    for axis in axes:
        _unregister_active_jog(axis)
    for axis in axes:
        stop_axis(axis)


def jog_keepalive(axes: List[int]) -> None:
    """Refresh the watchdog timer for ``axes``."""
    now = time.time()
    with _active_jogs_lock:
        for axis in axes:
            if axis in _active_jogs:
                _active_jogs[axis] = now

__all__ = [
    # Hardware-touching public API
    "jog_axis",
    "jog_stop",
    "jog_keepalive",
    "stop_axis",

    # State helpers (used by the watchdog and the tests)
    "snapshot_active_jogs",
    "clear_active_jogs",


    # Back-compat aliases
    "_active_jogs",
    "_active_jogs_lock",
]