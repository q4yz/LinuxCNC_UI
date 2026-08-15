"""Hardware connection layer — LinuxCNC NML channel wrapper.

This module is now a thin facade over the ``hardware.connection``
low-level helpers. The class-level abstractions (HAL-pin mapper,
HAL subscription manager, hardware-layer service) live in
dedicated sibling files inside the ``hardware/`` package:

  * :file:`hardware/device_config_mapper.py` — ``DeviceConfigMapper``
    (``.cfg`` → HAL pin translation, Layer 1).
  * :file:`hardware/hal_subscription-manager.py` —
    ``HalSubscriptionManager`` (HAL pin polling, Layer 0).
  * :class:`backend.services.machine_service.MachineService` —
    hardware-layer endstop + G-code facade (Layer 2).

This file only owns:

  * the lazy NML channel wrapper (``_LazyChannel``);
  * the linuxcnc / hal fallback module selection;
  * the public dispatch helpers (``execute_sync_cmd``,
    ``execute_gcode``);
  * the legacy :class:`Connection` object wrapper kept around
    because historical routers imported it;
  * the **mock-transparent** read/write helpers that production
    code uses to interact with telemetry buffers without knowing
    whether the underlying driver is the real LinuxCNC binding or
    the in-memory mock.

The ``Connection`` class, ``default_mapper``, ``hal_manager``, and
``machine_service`` re-exports below are kept for backward
compatibility — modern code imports the dedicated classes from
their canonical modules instead.
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
#
# Two distinct failure modes:
#
# 1. The ``linuxcnc`` package itself is missing (typical dev box).
#    We silently swap in ``linuxcnc_mock`` so the backend boots.
# 2. The package is installed but the NML channels are unreachable
#    (LinuxCNC not started yet). The constructor calls below would
#    raise ``linuxcnc.error``; we don't call them eagerly any more —
#    :class:`_LazyChannel` handles the reconnect on first use.
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
    """Connect to a LinuxCNC NML channel on first use; retry on failure.

    The wrapper holds ``None`` until the first successful call to
    :meth:`get`. On every call we honour an exponential-backoff
    window so a tight API-call loop cannot hammer a down NML server.

    The class is intentionally framework-agnostic so it can wrap any
    zero-argument constructor that may raise ``linuxcnc.error`` (or
    any other exception) while the underlying service is offline.
    """

    INITIAL_BACKOFF_S = 1.0
    MAX_BACKOFF_S = 30.0

    def __init__(self, ctor_name: str) -> None:
        self._ctor_name = ctor_name
        self._ctor: Callable[[], Any] = getattr(linuxcnc, ctor_name)
        self._cached: Optional[Any] = None
        self._lock = threading.Lock()
        self._last_error_at: Optional[float] = None
        self._backoff_s: float = self.INITIAL_BACKOFF_S
        # Track connect attempts so the first call after boot does
        # not log a spurious "still failing" warning on a healthy
        # channel that just hasn't been connected yet.
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
        """Return the cached channel, connecting on first call.

        Returns ``None`` when the channel is currently unreachable;
        callers that expect a snapshot must tolerate ``None`` (the
        WebSocket layer does, via ``getattr(..., default)``).
        """
        if self._cached is not None:
            return self._cached
        with self._lock:
            if self._cached is not None:
                return self._cached
            self._attempt_count += 1
            # Honour the backoff window — do not retry more often
            # than ``_backoff_s`` after a failure.
            if self._last_error_at is not None:
                now = time.monotonic()
                if now - self._last_error_at < self._backoff_s:
                    return None
            try:
                self._cached = self._ctor()
            except Exception as exc:  # noqa: BLE001 - linuxcnc.error is broad
                self._record_failure(exc)
                return None
            self._record_success()
            logger.info(
                "linuxcnc.%s() connected.", self._ctor_name,
            )
            return self._cached

    def is_connected(self) -> bool:
        """Return ``True`` iff the channel has connected at least once."""
        return self._cached is not None


# Module-level aliases for tests and consumers that want to align
# their backoff with the wrapper without importing the private class.
INITIAL_BACKOFF_S = _LazyChannel.INITIAL_BACKOFF_S
MAX_BACKOFF_S = _LazyChannel.MAX_BACKOFF_S

_stat_ch = _LazyChannel("stat")
_cmd_ch = _LazyChannel("command")
_error_ch = _LazyChannel("error_channel")


# ---------------------------------------------------------------------------
# Public Helper Functions (Layer 0)
# ---------------------------------------------------------------------------


def get_machine_stat():
    """Return the LinuxCNC status channel, connecting on first call.

    May return ``None`` while LinuxCNC is offline; callers that need
    a snapshot must tolerate ``None`` (the WebSocket telemetry loop
    does, via ``getattr(machine_stat, 'attr', default)``).
    """
    return _stat_ch.get()


def get_machine_cmd():
    """Return the LinuxCNC command channel, connecting on first call.

    May return ``None`` while LinuxCNC is offline. Callers that
    need to dispatch a command must check for ``None`` first (the
    standard :func:`execute_sync_cmd` helper does this and raises
    ``HTTPException(503)``).
    """
    return _cmd_ch.get()


def get_machine_error():
    """Return the LinuxCNC error channel, connecting on first call.

    May return ``None`` while LinuxCNC is offline.
    """
    return _error_ch.get()


def is_linuxcnc_connected() -> bool:
    """Return ``True`` iff every NML channel has connected at least once.

    Useful for the WebSocket telemetry layer to surface an "offline"
    banner to the operator without trying to read attributes off a
    ``None`` channel.
    """
    return (
        _stat_ch.is_connected()
        and _cmd_ch.is_connected()
        and _error_ch.is_connected()
    )


def execute_gcode(gcode: str, timeout: float = 10.0) -> dict:
    """Execute raw G-code via LinuxCNC MDI mode and return result state.

    Sets the task mode to ``MDI`` (when not already there) before
    dispatching so a stale ``MODE_AUTO`` does not silently swallow
    the command. Mirrors the historical ``execute_sync_cmd("mdi")``
    helper but exposes the timeout as a parameter — 10 s is the
    historical default for "G28 home all" / similar long moves.

    Raises:
        HTTPException: 503 when the command / stat channel is
            offline; 400 on LinuxCNC RCS_ERROR (parse / execution);
            408 on timeout; 500 on any other failure.
    """
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
    """Dispatch ``cmd_name`` to the LinuxCNC command channel.

    Mirrors the historical contract with one addition: when the
    command channel has not yet connected (LinuxCNC not running)
    the helper raises ``HTTPException(503)`` so the FastAPI layer
    surfaces a clear "service unavailable" response instead of the
    backend crashing.

    Raises:
        HTTPException: 503 when the command channel is offline;
            500 when the command name is unknown to the hardware
            layer; 408 on timeout; 500 on any other failure.
    """
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
            # wait_complete blocks until the command is processed by LinuxCNC
            ret = cmd.wait_complete(cmd_timeout)
            if ret == getattr(linuxcnc, "RCS_DONE", 1):
                return {"status": "success"}
            elif ret == getattr(linuxcnc, "RCS_ERROR", 3):
                raise HTTPException(
                    status_code=400, detail="Command execution error"
                )
            else:
                raise HTTPException(
                    status_code=408, detail="Command timed out"
                )
        else:
            return {"status": "success"}
    except AttributeError:
        raise HTTPException(
            status_code=500,
            detail=f"Command '{cmd_name}' not implemented in hardware interface.",
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - defensive catch-all
        logger.error(f"Command execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Mock-transparent telemetry helpers
# ---------------------------------------------------------------------------
#
# These helpers give production code a single read/write surface
# that works regardless of whether the underlying driver is the
# real ``linuxcnc`` binding or the in-memory mock. On real hardware
# the fields are absent (real LinuxCNC doesn't carry an in-process
# RPM telemetry buffer or bounded error history) so the helpers
# degrade to ``None`` / ``[]`` / no-ops — callers stay mock-agnostic.
#
# The mock implements the same surface through ``stat`` (read
# snapshots) and dedicated ``update_*`` / ``push_error`` helpers.
# Production code never imports :mod:`hardware.linuxcnc_mock`
# directly.


def read_temperature(sensor_id: str) -> Optional[Dict[str, float]]:
    """Return ``{actual, target}`` for ``sensor_id`` or ``None``.

    Reads from the live ``stat`` channel so the same call works on
    real LinuxCNC and the mock. The mock's :class:`stat` mirrors
    its in-process sensor dict on every ``poll()``; real LinuxCNC
    exposes the same dict via ``stat.temperatures``. ``None`` is
    returned for unknown sensors / non-string ids / offline channel.
    """
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
    """Return a shallow list copy of the bounded error history.

    The mock tracks a bounded ``errors`` queue in :class:`stat` so a
    reload / reconnect re-hydrates the operator console with the
    recent session history. Real LinuxCNC has no equivalent buffer
    (its NML error channel drains into the WS layer live), so this
    returns ``[]`` on a real driver.
    """
    stat = get_machine_stat()
    if stat is None:
        return []
    poll = getattr(stat, "poll", None)
    if callable(poll):
        poll()
    return list(getattr(stat, "errors", []) or [])


def read_hal_pin(pin_name: str) -> Optional[object]:
    """Read the current live value of a LinuxCNC HAL pin or signal."""
    if hal is None:
        return None

    try:
        # hal.get_value reads pins, signals, and parameters dynamically.
        return hal.get_value(pin_name)
    except Exception as e:
        # Logged as debug so it doesn't spam the console if the VFD
        # component isn't loaded yet during boot.
        logger.debug("Failed to read HAL pin '%s': %s", pin_name, e)
        return None


def mark_spindle_connected(tool_id: str, is_connected: bool) -> None:
    """Flip the spindle's ``is_connected`` flag immediately.

    On the mock this eagerly updates ``stat.spindle_actual[tool_id]``
    so the dashboard's SpindleCard reflects the operator's command
    before the next HAL poll tick (the simulator refines ``actual``
    on the following iteration). On real hardware this is a no-op —
    real LinuxCNC doesn't carry an in-process ``is_connected`` flag;
    the VFD status comes from HAL pins directly.
    """
    if not isinstance(tool_id, str) or not tool_id:
        return
    if not USE_MOCK:
        return
    from . import linuxcnc_mock  # local import keeps mock off the hot path on real hw

    linuxcnc_mock.update_spindle_connected(tool_id, bool(is_connected))


def push_machine_error(kind: int, text: str, time: str) -> None:
    """Record a LinuxCNC error-channel event into the bounded history.

    On the mock this calls :meth:`linuxcnc_mock.error_channel.poll`
    which appends to the bounded ``errors`` queue. Real LinuxCNC
    doesn't carry an in-process history (its error channel is
    consume-once), so the helper is a no-op there.
    """
    if not USE_MOCK:
        return
    from . import linuxcnc_mock  # local import keeps mock off the hot path on real hw

    linuxcnc_mock.record_error(kind, text, time)


def push_spindle_telemetry(
    tool_id: str,
    *,
    actual: Optional[int] = None,
    is_connected: Optional[bool] = None,
    error_count: Optional[int] = None,
) -> None:
    """Apply the given fields to ``stat.spindle_actual[tool_id]``.

    Used by the HAL-pin subscription callback (per-tick telemetry)
    and any future writer. On the mock this updates
    ``_machine_state.spindle_actual`` under its lock and is mirrored
    into ``stat.spindle_actual`` on the next ``poll()``. On real
    hardware this is a no-op — the live VFD status arrives via HAL
    pins directly and there is no in-process buffer to update.
    """
    if not isinstance(tool_id, str) or not tool_id:
        return
    if not USE_MOCK:
        return
    from . import linuxcnc_mock  # local import keeps mock off the hot path on real hw

    linuxcnc_mock.update_spindle_telemetry(
        tool_id,
        actual=actual,
        is_connected=is_connected,
        error_count=error_count,
    )


def apply_spindle_pin(tool_id: str, pin_name: str, pin_value: Any) -> None:
    """Translate one HAL pin read into spindle telemetry fields.

    Used by the per-tick HAL subscription callback. The mock owns
    the per-pin field mapping (``rpm_out`` → ``actual``, ``on`` /
    ``vfd_enable`` → ``is_connected``, ``istop`` / ``estop`` →
    ``error_count`` delta). On real hardware this is a no-op —
    the live VFD status arrives via HAL pins directly and there is
    no in-process ``spindle_actual`` buffer to update.
    """
    if not isinstance(tool_id, str) or not tool_id:
        return
    if not USE_MOCK:
        return
    from . import linuxcnc_mock  # local import keeps mock off the hot path on real hw

    linuxcnc_mock.apply_spindle_pin(tool_id, pin_name, pin_value)


# ---------------------------------------------------------------------------
# Connection facade object (legacy compatibility)
# ---------------------------------------------------------------------------


class Connection:
    """Legacy Object wrapper for backwards compatibility.

    The historical router imported :data:`connection` and called
    methods on it (``connection.get_machine_stat()``,
    ``connection.execute_sync_cmd(...)``). Modern code imports the
    module-level helpers directly (e.g. ``get_machine_stat``,
    ``execute_sync_cmd``) so this wrapper exists only for the
    historical call sites.
    """

    def get_machine_stat(self):
        return get_machine_stat()

    def get_machine_cmd(self):
        return get_machine_cmd()

    def get_machine_error(self):
        return get_machine_error()

    def is_linuxcnc_connected(self) -> bool:
        return is_linuxcnc_connected()

    def execute_sync_cmd(
        self, cmd_name: str, cmd_timeout: float = 0, *args
    ) -> dict:
        return execute_sync_cmd(cmd_name, cmd_timeout, *args)


connection = Connection()


# ---------------------------------------------------------------------------
# Re-exports for backward compatibility
# ---------------------------------------------------------------------------
#
# The class-level abstractions used to live inline here. After the
# previous round split them into dedicated sibling files, this
# module kept duplicate definitions (a tech-debt cleanup item).
# This re-export block makes the canonical modules the single source
# of truth while preserving ``from hardware.connection import X``
# for any consumer that hasn't migrated yet.

from .device_config_mapper import DeviceConfigMapper  # noqa: E402,F401
from .hal_subscription_manager import (  # noqa: E402,F401
    HalSubscriptionManager,
    hal_manager,
)
# ``MachineService`` / ``machine_service`` / ``default_mapper``
# live in ``services.machine_service`` (the hardware-folder
# facade) and are NOT re-exported here to avoid the
# ``services.machine_service`` ↔ ``hardware.connection`` circular
# import. Consumers that need them should import from
# ``services.machine_service`` directly.


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
    "read_spindle_telemetry",
    "read_error_history",
    "mark_spindle_connected",
    "push_machine_error",
    "push_spindle_telemetry",
    "apply_spindle_pin",
    "Connection",
    "connection",
    "DeviceConfigMapper",
    "HalSubscriptionManager",
    "hal_manager",
    # Note: ``MachineService`` / ``machine_service`` /
    # ``default_mapper`` are intentionally NOT re-exported here to
    # avoid the ``services.machine_service`` ↔
    # ``hardware.connection`` circular import. Import them from
    # ``services.machine_service`` directly.
]