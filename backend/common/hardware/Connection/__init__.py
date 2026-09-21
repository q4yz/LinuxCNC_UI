"""Hardware connection layer — package facade.

Split out of the historical monolithic ``hardware/Connection.py`` into
four files with a strictly unidirectional dependency graph:

  * ``core.py`` — mock fallbacks, enums, the lazy NML channel wrapper
    (``_LazyChannel``), and the HAL pin read choke point.
  * ``channel_stat.py`` — thread-local ``stat`` channel management.
  * ``channel_error.py`` — thread-local ``error_channel`` management
    + error-history retrieval (depends on ``channel_stat`` for its
    own ``stat.poll()`` call).
  * ``channel_cmd.py`` — the shared ``command`` channel, the dispatch
    lock, and the public ``execute_gcode``/``execute_sync_cmd``
    dispatchers (depends on ``channel_stat`` for the MDI-mode-switch
    preamble).

This package is still imported everywhere in the codebase as
``hardware.Connection`` (capital C) — the directory is named to match
exactly, not ``hardware/connection/`` — because every call site
(``from hardware.Connection import ...``, ``from hardware import
...`` via ``hardware/__init__.py``'s own ``from .Connection import
...``) resolves that name case-sensitively on the real Linux
deployment target. A lowercase package directory would silently work
on a case-insensitive dev filesystem (Windows/mac) and then fail every
one of those imports the moment it actually ran on the Pi. This
``__init__.py`` re-exports the full original flat-module surface —
including the handful of "private" names (``_LazyChannel``, ``_cmd_ch``,
``INITIAL_BACKOFF_S``) that ``test_connection_lazy.py`` imports
directly — so no caller anywhere in the app needed to change.
"""
from __future__ import annotations

from .core import (
    USE_MOCK,
    HAS_HAL,
    hal,
    linuxcnc,
    MachineState,
    MachineMode,
    RcsStatus,
    _LazyChannel,
    INITIAL_BACKOFF_S,
    MAX_BACKOFF_S,
    read_hal_pin,
)
from .channel_stat import get_stat_channel, is_stat_connected
from .channel_error import get_error_channel, is_error_connected, read_error_history
from .channel_cmd import (
    _cmd_ch,
    get_cmd_channel,
    is_cmd_connected,
    execute_gcode,
    execute_sync_cmd,
    ensure_mdi_mode,
)
from ..DeviceConfigMapper import DeviceConfigMapper


def is_linuxcnc_connected() -> bool:
    """Check if this thread's NML channels have successfully connected.

    ``stat``/``error_channel`` are per-thread (see ``channel_stat.py``)
    — this reports the calling thread's own connection state for
    those two, plus the shared ``command`` channel's.
    """
    return is_stat_connected() and is_cmd_connected() and is_error_connected()


__all__ = [
    "USE_MOCK",
    "HAS_HAL",
    "hal",
    "linuxcnc",
    "is_linuxcnc_connected",
    "execute_sync_cmd",
    "execute_gcode",
    "ensure_mdi_mode",
    "read_error_history",
    "read_hal_pin",
    "DeviceConfigMapper",
    "MachineState",
    "MachineMode",
    "RcsStatus",
    "get_stat_channel",
    "get_cmd_channel",
    "get_error_channel",
]
