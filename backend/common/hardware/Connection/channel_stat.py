"""Thread-local LinuxCNC status (``stat``) channel management.

One independent ``_LazyChannel`` per calling thread rather than a
single shared global. ``stat`` is a read-only NML status buffer — real
LinuxCNC explicitly supports any number of independent simultaneous
readers (AXIS, halui, ``halcmd`` and a custom script routinely poll
``stat()`` concurrently against the same machine with zero
coordination needed). The freeze this fixed was never NML-level
contention — it was a single cached ``stat`` object having ``.poll()``
called on it concurrently from multiple OS threads at once (the
asyncio event-loop thread via ``ServoThreadService.telemetry_loop`` at
10 Hz, and every Starlette threadpool worker thread dispatching a sync
HTTP handler that reads status — base-thread snapshot, program
progress, macro execution). LinuxCNC's Python NML bindings are not
documented as thread-safe for concurrent calls on one object; giving
each thread its own handle removes that hazard with no lock and no
added latency, since independent readers never wait on each other.
"""
from __future__ import annotations

import threading
from typing import Any, Optional

from .core import _LazyChannel

_thread_local = threading.local()


def _thread_stat_channel() -> _LazyChannel:
    """This calling thread's own `stat` channel wrapper (lazy)."""
    channel = getattr(_thread_local, "stat_ch", None)
    if channel is None:
        channel = _LazyChannel("stat")
        _thread_local.stat_ch = channel
    return channel


def get_stat_channel() -> Optional[Any]:
    """Retrieve the calling thread's own LinuxCNC status channel.

    One independent NML connection per thread — see module docstring
    for why this is not a single shared global.
    """
    return _thread_stat_channel().get()


def is_stat_connected() -> bool:
    """Whether the calling thread's own `stat` channel has connected."""
    return _thread_stat_channel().is_connected()


__all__ = ["get_stat_channel", "is_stat_connected"]
