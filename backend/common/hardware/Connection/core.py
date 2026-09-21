"""Core connection primitives: mock fallbacks, enums, the lazy NML
channel wrapper, and the HAL pin read choke point.

Split out of the historical monolithic ``hardware/Connection.py`` so
mock routing, thread-local channel management, and command-dispatch
locking each live in their own file with a strictly unidirectional
dependency graph — this file has no dependency on any sibling in the
package; ``channel_stat``/``channel_error``/``channel_cmd`` all
depend on it, never the other way around.
"""
from __future__ import annotations

import threading
import time
from enum import IntEnum
from typing import Any, Callable, Optional

from core.non_repeating_logger import NonRepeatingLogger

logger = NonRepeatingLogger("backend.hardware.connection.core")

# ---------------------------------------------------------------------------
# Module selection: real linuxcnc/hal vs. mock fallback
# ---------------------------------------------------------------------------
try:
    import linuxcnc  # noqa: F401

    logger.info("Successfully imported real linuxcnc module.")
    USE_MOCK = False
except ImportError:
    from hardware.mock.LinuxCNCMock import linuxcnc

    logger.warning("Could not import real linuxcnc. Falling back to mock facade.")
    USE_MOCK = True

try:
    import hal

    HAS_HAL = True
except ImportError:
    from hardware.mock.LinuxCNCMock import hal

    HAS_HAL = False
    logger.warning("HAL module unavailable; HAL pin polling will run in mock mode.")


# ---------------------------------------------------------------------------
# Domain Enums (Encapsulating LinuxCNC Constants)
# ---------------------------------------------------------------------------
class MachineState(IntEnum):
    """Standard task states."""
    ESTOP = getattr(linuxcnc, "STATE_ESTOP", 1)
    ESTOP_RESET = getattr(linuxcnc, "STATE_ESTOP_RESET", 2)
    OFF = getattr(linuxcnc, "STATE_OFF", 3)
    ON = getattr(linuxcnc, "STATE_ON", 4)


class MachineMode(IntEnum):
    """Standard task modes."""
    MANUAL = getattr(linuxcnc, "MODE_MANUAL", 1)
    AUTO = getattr(linuxcnc, "MODE_AUTO", 2)
    MDI = getattr(linuxcnc, "MODE_MDI", 3)


class RcsStatus(IntEnum):
    """Return status codes for NML commands."""
    DONE = getattr(linuxcnc, "RCS_DONE", 1)
    EXEC = getattr(linuxcnc, "RCS_EXEC", 2)
    ERROR = getattr(linuxcnc, "RCS_ERROR", 3)


# ---------------------------------------------------------------------------
# Lazy channel wrapper (Layer 0: Low-Level Connection)
# ---------------------------------------------------------------------------
class _LazyChannel:
    """Connect to a LinuxCNC NML channel on first use; retry on failure."""

    INITIAL_BACKOFF_S = 1.0
    MAX_BACKOFF_S = 30.0

    def __init__(self, ctor_name: str) -> None:
        self._ctor_name = ctor_name
        self._ctor: Callable[[], Any] = getattr(linuxcnc, ctor_name)
        self._cached: Optional[Any] = None
        self._lock = threading.Lock()
        self._last_error_at: Optional[float] = None
        self._backoff_s: float = self.INITIAL_BACKOFF_S
        self._attempt_count: int = 0

    def _record_failure(self, exc: BaseException) -> None:
        """Note a failed attempt and adjust the backoff window."""
        self._last_error_at = time.monotonic()
        self._backoff_s = min(self._backoff_s * 2, self.MAX_BACKOFF_S)
        logger.warning("linuxcnc.%s() unavailable (%s) — backend will keep running " "and retry in %.1fs.",self._ctor_name,exc,self._backoff_s)

    def _record_success(self) -> None:
        """Reset backoff on a successful connect."""
        if self._backoff_s != self.INITIAL_BACKOFF_S:
            logger.info(  "linuxcnc.%s() reconnected after %d failed attempt(s).",self._ctor_name,self._attempt_count)
        self._backoff_s = self.INITIAL_BACKOFF_S
        self._last_error_at = None

    def get(self) -> Optional[Any]:
        """Return the cached channel, connecting on first call."""
        if self._cached is not None:
            return self._cached

        with self._lock:
            if self._cached is not None:
                return self._cached

            self._attempt_count += 1
            if self._last_error_at is not None:
                now = time.monotonic()
                if now - self._last_error_at < self._backoff_s:
                    return None

            try:
                self._cached = self._ctor()
            except Exception as exc:  # noqa: BLE001
                self._record_failure(exc)
                return None

            self._record_success()
            logger.info("linuxcnc.%s() connected.", self._ctor_name)
            return self._cached

    def is_connected(self) -> bool:
        """Return ``True`` iff the channel has connected at least once."""
        return self._cached is not None


INITIAL_BACKOFF_S = _LazyChannel.INITIAL_BACKOFF_S
MAX_BACKOFF_S = _LazyChannel.MAX_BACKOFF_S


# ---------------------------------------------------------------------------
# HAL pin read — single choke point, mirrors _LazyChannel's role for
# NML channels. See channel_cmd.py's module docstring for the fuller
# reliability-audit reasoning this was born from.
# ---------------------------------------------------------------------------
class _HalReadConnection:
    """Single choke point for reading a named HAL pin via
    ``hal.get_value`` — mirrors ``_LazyChannel``'s role for NML
    channels.

    No lock today: ``hal.get_value()`` is a stateless named-pin
    lookup, not a connection with in-flight state the way NML's
    ``command`` channel is, and it's never called from the async
    event loop — only from threadpool-dispatched sync handlers (the
    1Hz base-thread snapshot's tools/sensors overlay). Worst case on
    a genuine concurrent read is one stale/bad sample that
    self-corrects on the next poll, not a freeze. Wrapping it in one
    object now means a lock can be added here later, if real evidence
    of contention ever shows up, without touching every ``HalPin``
    subclass that reads a pin.
    """

    def read(self, pin_name: str) -> Optional[Any]:
        if hal is None:
            return None
        try:
            return hal.get_value(pin_name)
        except Exception as e:
            logger.debug("Failed to read HAL pin '%s': %s", pin_name, e)
            return None


_hal_read_ch = _HalReadConnection()


def read_hal_pin(pin_name: str) -> Optional[Any]:
    """
    Read the current value of a specific HAL pin.

    Args:
        pin_name (str): The exact name of the HAL pin.

    Returns:
        The value of the pin (float, int, bool) or None if unreadable.
    """
    return _hal_read_ch.read(pin_name)


__all__ = [
    "USE_MOCK",
    "HAS_HAL",
    "hal",
    "linuxcnc",
    "MachineState",
    "MachineMode",
    "RcsStatus",
    "_LazyChannel",
    "INITIAL_BACKOFF_S",
    "MAX_BACKOFF_S",
    "read_hal_pin",
]
