"""Hardware connection layer — LinuxCNC NML channel wrapper.

This module is now a thin facade over the ``hardware.connection``
low-level helpers. The class-level abstractions (HAL-pin mapper,
HAL subscription manager, hardware-layer service) live in
dedicated sibling files inside the ``hardware/`` package.

This file only owns:
  * the lazy NML channel wrapper (``_LazyChannel``);
  * the linuxcnc / hal fallback module selection;
  * the public dispatch helpers (``execute_sync_cmd``, ``execute_gcode``);
  * the legacy :class:`Connection` object wrapper.

The module is strictly mock-agnostic. It communicates with the driver
exclusively through the standard `linuxcnc` and `hal` Python APIs,
treating real hardware and the local simulator identically.
"""
from __future__ import annotations

import sys
import threading
import time
from enum import IntEnum
from typing import Any, Callable, Optional, Dict, List

from fastapi import HTTPException

from core.non_repeating_logger import NonRepeatingLogger

logger = NonRepeatingLogger("backend.hardware.connection")

# ---------------------------------------------------------------------------
# Module selection: real linuxcnc/hal vs. mock fallback
# ---------------------------------------------------------------------------
try:
    import linuxcnc  # noqa: F401

    logger.info("Successfully imported real linuxcnc module.")
    USE_MOCK = False
except ImportError:
    from hardware.mock.LinuxCNCMock import linuxcnc  # type: ignore

    logger.warning("Could not import real linuxcnc. Falling back to mock facade.")
    USE_MOCK = True

try:
    import hal

    HAS_HAL = True
except ImportError:
    from hardware.mock.LinuxCNCMock import hal  # type: ignore[no-redef]

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

_stat_ch = _LazyChannel("stat")
_cmd_ch = _LazyChannel("command")
_error_ch = _LazyChannel("error_channel")


# ---------------------------------------------------------------------------
# Private Helper Functions (Subfunctions)
# ---------------------------------------------------------------------------
def _wait_for_completion(cmd_channel: Any, timeout: float) -> None:
    """
    Block until the LinuxCNC command completes, fails, or times out.

    Args:
        cmd_channel: The active LinuxCNC command channel.
        timeout (float): The maximum time to wait in seconds.

    Raises:
        HTTPException (400): If the command returns an execution error.
        HTTPException (408): If the command exceeds the timeout.
    """
    if timeout <= 0:
        return

    result = cmd_channel.wait_complete(timeout)

    if result == RcsStatus.DONE:
        return
    elif result == RcsStatus.ERROR:
        raise HTTPException(status_code=400, detail="Command execution error")
    else:
        raise HTTPException(status_code=408, detail="Command timed out")


def _switch_to_mdi_mode(stat_channel: Any, cmd_channel: Any) -> None:
    """
    Safely switch the machine to MDI mode if it is not already in it.

    Args:
        stat_channel: The active LinuxCNC status channel.
        cmd_channel: The active LinuxCNC command channel.
    """
    stat_channel.poll()
    if stat_channel.task_mode != MachineMode.MDI:
        cmd_channel.mode(MachineMode.MDI)
        _wait_for_completion(cmd_channel, timeout=1.0)


# ---------------------------------------------------------------------------
# Public Accessors
# ---------------------------------------------------------------------------
def get_stat_channel() -> Optional[Any]:
    """Retrieve the underlying LinuxCNC status channel."""
    return _stat_ch.get()


def get_cmd_channel() -> Optional[Any]:
    """Retrieve the underlying LinuxCNC command channel."""
    return _cmd_ch.get()


def get_error_channel() -> Optional[Any]:
    """Retrieve the underlying LinuxCNC error channel."""
    return _error_ch.get()


def is_linuxcnc_connected() -> bool:
    """Check if all LinuxCNC NML channels have successfully connected."""
    return (
        _stat_ch.is_connected()
        and _cmd_ch.is_connected()
        and _error_ch.is_connected()
    )


# ---------------------------------------------------------------------------
# Public Execution Commands
# ---------------------------------------------------------------------------
def execute_gcode(gcode: str, timeout: float = 10.0) -> Dict[str, Any]:
    """
    Execute raw G-code via LinuxCNC MDI mode.

    Automatically switches the machine to MDI mode if required, sends the
    command, and awaits completion.

    Args:
        gcode (str): The G-code string to execute.
        timeout (float): The maximum wait time in seconds. Defaults to 10.0.

    Returns:
        dict: A status dictionary containing the executed G-code.

    Raises:
        HTTPException (503): If the LinuxCNC channels are unavailable.
        HTTPException (400): If the G-code triggers an execution error.
        HTTPException (408): If the command times out.
        HTTPException (500): On unexpected internal errors.
    """
    cmd = get_cmd_channel()
    stat = get_stat_channel()

    if cmd is None or stat is None:
        raise HTTPException(
            status_code=503,
            detail="LinuxCNC is not running. Start LinuxCNC and retry.",
        )

    try:
        _switch_to_mdi_mode(stat, cmd)
        cmd.mdi(gcode)

        # We catch the inner exception from _wait_for_completion
        # and re-raise it with G-Code specific context if needed.
        try:
            _wait_for_completion(cmd, timeout)
        except HTTPException as he:
            if he.status_code == 400:
                raise HTTPException(status_code=400, detail=f"G-code execution error: {gcode}")
            raise

        return {"status": "success", "gcode": gcode}

    except HTTPException:
        # Re-raise known API errors (400, 408, 503) cleanly
        raise
    except Exception as e:  # noqa: BLE001
        logger.error("G-code execution failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


def execute_sync_cmd(cmd_name: str, timeout: float = 0, *args) -> Dict[str, str]:
    """
    Dispatch a named command directly to the LinuxCNC command channel.

    Args:
        cmd_name (str): The exact name of the method to call on the command channel.
        timeout (float): How long to wait for completion in seconds (0 for async).
        *args: Variable arguments to pass to the command method.

    Returns:
        dict: A success status dictionary `{"status": "success"}`.

    Raises:
        HTTPException (503): If the LinuxCNC command channel is unavailable.
        HTTPException (500): If the command does not exist or an internal error occurs.
        HTTPException (400): If the command returns an execution error.
        HTTPException (408): If the command exceeds `timeout`.
    """
    cmd = get_cmd_channel()
    if cmd is None:
        raise HTTPException(status_code=503, detail="LinuxCNC is not running. Start LinuxCNC and retry.")

    # 1. Resolve command binding
    try:
        func = getattr(cmd, cmd_name)
    except AttributeError:
        raise HTTPException(status_code=500, detail=f"Command '{cmd_name}' not implemented in hardware interface.")

    # 2. Execute and wait
    try:
        func(*args)
        _wait_for_completion(cmd, timeout)
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"Command execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def ensure_mdi_mode() -> None:
    """Force the machine into MDI mode immediately with a standard 5-second timeout."""
    execute_sync_cmd("mode", 5.0, MachineMode.MDI)


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


def read_hal_pin(pin_name: str) -> Optional[Any]:
    """
    Read the current value of a specific HAL pin.

    Args:
        pin_name (str): The exact name of the HAL pin.

    Returns:
        The value of the pin (float, int, bool) or None if unreadable.
    """
    if hal is None:
        return None
    try:
        return hal.get_value(pin_name)
    except Exception as e:
        logger.debug("Failed to read HAL pin '%s': %s", pin_name, e)
        return None



# ---------------------------------------------------------------------------
# Re-exports for backward compatibility
# ---------------------------------------------------------------------------
from .DeviceConfigMapper import DeviceConfigMapper  # noqa: E402,F401
from .HalSubscriptionManager import (  # noqa: E402,F401
    HalSubscriptionManager,
    hal_manager,
)

# NOTICE: 'linuxcnc' has been removed from this list!
__all__ = [
    "USE_MOCK",
    "HAS_HAL",
    "hal",
    "linuxcnc",
    "is_linuxcnc_connected",
    "execute_sync_cmd",
    "execute_gcode",
    "read_error_history",
    "DeviceConfigMapper",
    "HalSubscriptionManager",
    "hal_manager",
    "MachineState",
    "MachineMode",
    "RcsStatus",
    "get_stat_channel",
    "get_cmd_channel",
    "get_error_channel",
]