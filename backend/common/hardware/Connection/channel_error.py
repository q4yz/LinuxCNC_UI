"""Thread-local LinuxCNC error-channel management + history retrieval.

Same per-thread rationale as ``channel_stat.py`` — ``error_channel``
is the other read-only NML status buffer, and shares the exact same
concurrent-reader-safety story.
"""
from __future__ import annotations

import threading
from typing import Any, List, Optional

from .core import _LazyChannel, linuxcnc
from .channel_stat import get_stat_channel

_thread_local = threading.local()


def _thread_error_channel() -> _LazyChannel:
    """This calling thread's own `error_channel` wrapper (lazy)."""
    channel = getattr(_thread_local, "error_ch", None)
    if channel is None:
        channel = _LazyChannel("error_channel")
        _thread_local.error_ch = channel
    return channel


def get_error_channel() -> Optional[Any]:
    """Retrieve the calling thread's own LinuxCNC error channel.

    One independent NML connection per thread — see
    ``channel_stat.py``'s module docstring for why this is not a
    single shared global.
    """
    return _thread_error_channel().get()


def is_error_connected() -> bool:
    """Whether the calling thread's own `error_channel` has connected."""
    return _thread_error_channel().is_connected()


def read_error_history() -> List[str]:
    """
    Poll the status channel and extract the machine error history.

    Returns:
        list: A list of error string messages from LinuxCNC.
    """
    stat = get_stat_channel()
    if stat is None:
        return []

    poll = getattr(stat, "poll", None)
    if callable(poll):
        poll()

    return list(getattr(stat, "errors", []) or [])


#: Error-channel kinds that carry an operator *message*, not a fault:
#: ``(MSG, ...)`` / ``(DEBUG, ...)`` in G-code arrive as
#: ``OPERATOR_DISPLAY``/``OPERATOR_TEXT``, their NML twins likewise.
#: ``(ABORT, ...)`` and real faults arrive as ``OPERATOR_ERROR`` /
#: ``NML_ERROR`` — same split AXIS makes. Resolved by name so the real
#: module and the mock agree without hard-coding the integers.
_MESSAGE_KIND_NAMES = ("NML_TEXT", "NML_DISPLAY", "OPERATOR_TEXT", "OPERATOR_DISPLAY")
_MESSAGE_KINDS = frozenset(
    getattr(linuxcnc, name) for name in _MESSAGE_KIND_NAMES if hasattr(linuxcnc, name)
)


def message_severity(kind: int) -> str:
    """``"info"`` for an operator message, ``"error"`` for everything else.

    Unknown kinds count as errors — misreporting a real fault as info
    is the worse mistake of the two.
    """
    return "info" if kind in _MESSAGE_KINDS else "error"


__all__ = ["get_error_channel", "is_error_connected", "read_error_history", "message_severity"]
