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

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

from fastapi import HTTPException

logger = logging.getLogger("backend.hardware.connection")

# ---------------------------------------------------------------------------
# Module selection: real linuxcnc/hal vs. mock fallback
# ---------------------------------------------------------------------------
try:
    import linuxcnc  # noqa: F401 - the canonical import path
    logger.info("Successfully imported real linuxcnc module.")
    USE_MOCK = False
except ImportError:
    from . import linuxcnc_mock as linuxcnc  # type: ignore[no-redef]
    logger.warning("Could not import real linuxcnc. Falling back to linuxcnc_mock.")
    USE_MOCK = True

try:
    import hal
    HAS_HAL = True
except ImportError:
    hal = None
    HAS_HAL = False
    logger.warning("HAL module unavailable; HAL pin polling will run in mock mode.")


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
        logger.warning(
            "linuxcnc.%s() unavailable (%s) — backend will keep running "
            "and retry in %.1fs.",
            self._ctor_name,
            exc,
            self._backoff_s,
        )

    def _record_success(self) -> None:
        """Reset backoff on a successful connect."""
        if self._backoff_s != self.INITIAL_BACKOFF_S:
            logger.info(
                "linuxcnc.%s() reconnected after %d failed attempt(s).",
                self._ctor_name,
                self._attempt_count,
            )
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
# Public Helper Functions (Layer 0)
# ---------------------------------------------------------------------------

def get_machine_stat():
    return _stat_ch.get()

def get_machine_cmd():
    return _cmd_ch.get()

def get_machine_error():
    return _error_ch.get()

def is_linuxcnc_connected() -> bool:
    return (
        _stat_ch.is_connected()
        and _cmd_ch.is_connected()
        and _error_ch.is_connected()
    )


def execute_gcode(gcode: str, timeout: float = 10.0) -> dict:
    """Execute raw G-code via LinuxCNC MDI mode and return result state."""
    cmd = get_machine_cmd()
    stat = get_machine_stat()

    if cmd is None or stat is None:
        raise HTTPException(
            status_code=503,
            detail="LinuxCNC is not running. Start LinuxCNC and retry.",
        )

    try:
        stat.poll()
        if stat.task_mode != linuxcnc.MODE_MDI:
            cmd.mode(linuxcnc.MODE_MDI)
            cmd.wait_complete(1.0)

        cmd.mdi(gcode)
        ret = cmd.wait_complete(timeout)

        if ret == getattr(linuxcnc, "RCS_DONE", 1):
            return {"status": "success", "gcode": gcode}
        if ret == getattr(linuxcnc, "RCS_ERROR", 3):
            raise HTTPException(
                status_code=400, detail=f"G-code execution error: {gcode}"
            )
        raise HTTPException(status_code=408, detail="G-code command timed out")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error("G-code execution failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


def execute_sync_cmd(cmd_name: str, cmd_timeout: float = 0, *args) -> dict:
    """Dispatch ``cmd_name`` to the LinuxCNC command channel."""
    cmd = _cmd_ch.get()
    if cmd is None:
        raise HTTPException(
            status_code=503,
            detail="LinuxCNC is not running. Start LinuxCNC and retry.",
        )
    try:
        func = getattr(cmd, cmd_name)
        func(*args)

        if cmd_timeout > 0:
            ret = cmd.wait_complete(cmd_timeout)
            if ret == getattr(linuxcnc, "RCS_DONE", 1):
                return {"status": "success"}
            elif ret == getattr(linuxcnc, "RCS_ERROR", 3):
                raise HTTPException(status_code=400, detail="Command execution error")
            else:
                raise HTTPException(status_code=408, detail="Command timed out")
        else:
            return {"status": "success"}
    except AttributeError:
        raise HTTPException(
            status_code=500,
            detail=f"Command '{cmd_name}' not implemented in hardware interface.",
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"Command execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def ensure_mdi_mode() -> None:
    mode_mdi = getattr(linuxcnc, "MODE_MDI", 3)
    execute_sync_cmd("mode", 5, mode_mdi)

# ---------------------------------------------------------------------------
# Telemetry read helpers
# ---------------------------------------------------------------------------
#
# These helpers read strictly from the standard APIs (`stat` and `hal`).
# They have no idea if they are talking to a mock or real hardware!

def read_temperature(sensor_id: str) -> Optional[Dict[str, float]]:
    if not isinstance(sensor_id, str) or not sensor_id:
        return None
    stat = get_machine_stat()
    if stat is None:
        return None
    poll = getattr(stat, "poll", None)
    if callable(poll):
        poll()
    sensors = getattr(stat, "temperatures", None) or {}
    reading = sensors.get(sensor_id)
    if not reading:
        return None
    return {
        "actual": float(reading.get("actual", 0.0)),
        "target": float(reading.get("target", 0.0)),
    }

def read_error_history() -> list:
    stat = get_machine_stat()
    if stat is None:
        return []
    poll = getattr(stat, "poll", None)
    if callable(poll):
        poll()
    return list(getattr(stat, "errors", []) or [])

def read_hal_pin(pin_name: str) -> Optional[object]:
    if hal is None:
        return None
    try:
        return hal.get_value(pin_name)
    except Exception as e:
        logger.debug("Failed to read HAL pin '%s': %s", pin_name, e)
        return None

# ---------------------------------------------------------------------------
# Connection facade object (legacy compatibility)
# ---------------------------------------------------------------------------

class Connection:
    def get_machine_stat(self):
        return get_machine_stat()

    def get_machine_cmd(self):
        return get_machine_cmd()

    def get_machine_error(self):
        return get_machine_error()

    def is_linuxcnc_connected(self) -> bool:
        return is_linuxcnc_connected()

    def execute_sync_cmd(self, cmd_name: str, cmd_timeout: float = 0, *args) -> dict:
        return execute_sync_cmd(cmd_name, cmd_timeout, *args)

connection = Connection()

# ---------------------------------------------------------------------------
# Re-exports for backward compatibility
# ---------------------------------------------------------------------------

from .device_config_mapper import DeviceConfigMapper  # noqa: E402,F401
from .hal_subscription_manager import (  # noqa: E402,F401
    HalSubscriptionManager,
    hal_manager,
)

__all__ = [
    "USE_MOCK",
    "HAS_HAL",
    "linuxcnc",
    "hal",
    "get_machine_stat",
    "get_machine_cmd",
    "get_machine_error",
    "is_linuxcnc_connected",
    "execute_sync_cmd",
    "execute_gcode",
    "read_temperature",
    "read_error_history",
    "Connection",
    "connection",
    "DeviceConfigMapper",
    "HalSubscriptionManager",
    "hal_manager",
]