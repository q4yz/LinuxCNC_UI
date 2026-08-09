import asyncio
import enum
import logging
import threading
from typing import Callable, List, Optional

from fastapi import HTTPException

logger = logging.getLogger("backend.hardware.connection")


# ---------------------------------------------------------------------- #
# Connection state machine                                                #
# ---------------------------------------------------------------------- #


class ConnectionState(str, enum.Enum):
    """Lifecycle states for the LinuxCNC binding.

    The string values mirror the acceptance criteria on issue #104 so
    callers can serialise the state verbatim (e.g. into the telemetry
    WebSocket payload or a ``/system/health`` endpoint).

    * ``READY``  — the ``stat`` / ``command`` / ``error_channel``
      objects are bound and ``poll()`` succeeded.
    * ``LINUXCNC_DISCONNECTED`` — the bind failed (or a previously
      successful bind later started failing). The background retry
      loop will keep trying to reconnect.
    * ``UNKNOWN`` — the initial bind has not been attempted yet.
      This is the value present for a few microseconds at import
      time before the synchronous initial probe completes.
    """

    READY = "READY"
    LINUXCNC_DISCONNECTED = "LINUXCNC_DISCONNECTED"
    UNKNOWN = "UNKNOWN"


# Thread-safe state holder. The retry loop runs on the asyncio event
# loop, but we still keep a lock so synchronous callers (e.g. tests,
# the ``execute_sync_cmd`` shortcut) cannot race the retry loop.
_state: ConnectionState = ConnectionState.UNKNOWN
_state_lock = threading.Lock()
_state_listeners: List[Callable[[ConnectionState], None]] = []


def get_connection_state() -> ConnectionState:
    """Return the current LinuxCNC connection state.

    This is the public read-only accessor used by the telemetry loop
    and the ``/system/health`` endpoint. The state is a snapshot of
    the most recent successful bind attempt.
    """
    with _state_lock:
        return _state


def add_state_listener(callback: Callable[[ConnectionState], None]) -> None:
    """Register a callback invoked when the state transitions.

    The callback receives the new state. It is invoked synchronously
    on whichever thread performed the state change (typically the
    asyncio retry loop). Exceptions raised by the callback are
    logged and swallowed so a buggy listener cannot break the
    retry loop.
    """
    with _state_lock:
        _state_listeners.append(callback)


def remove_state_listener(callback: Callable[[ConnectionState], None]) -> None:
    """Remove a previously registered state-change listener."""
    with _state_lock:
        if callback in _state_listeners:
            _state_listeners.remove(callback)


def _set_state(new_state: ConnectionState) -> None:
    """Update the state and notify listeners (no-op if unchanged)."""
    global _state
    with _state_lock:
        if _state == new_state:
            return
        old_state = _state
        _state = new_state
        listeners = list(_state_listeners)
    logger.info(
        "LinuxCNC connection state: %s -> %s",
        old_state.value,
        new_state.value,
    )
    for listener in listeners:
        try:
            listener(new_state)
        except Exception as exc:  # noqa: BLE001 - defensive
            logger.error("Connection state listener raised: %s", exc)


# ---------------------------------------------------------------------- #
# Hardware import (real linuxcnc vs mock)                                 #
# ---------------------------------------------------------------------- #


try:
    import linuxcnc as _real_linuxcnc
    logger.info("Successfully imported real linuxcnc module.")
    USE_MOCK = False
    linuxcnc = _real_linuxcnc
except ImportError:
    from . import linuxcnc_mock as _linuxcnc_mock
    logger.warning("Could not import real linuxcnc. Falling back to linuxcnc_mock.")
    USE_MOCK = True
    linuxcnc = _linuxcnc_mock


# ---------------------------------------------------------------------- #
# Bind / reconnect helpers                                                #
# ---------------------------------------------------------------------- #


# Module-level stat / command / error holders. Each may be ``None``
# while the connection is in ``LINUXCNC_DISCONNECTED`` state.
_machine_stat = None
_machine_cmd = None
_machine_error = None


# Optional injected MachineConfig instance (set during FastAPI startup)
machine_config = None


def _try_bind() -> bool:
    """Attempt to bind to LinuxCNC.

    On success, the module-level ``_machine_stat`` / ``_machine_cmd``
    / ``_machine_error`` are populated and the function returns
    ``True``. On any failure (the LinuxCNC process is not running,
    the NML socket is unreachable, the mock is misconfigured, ...)
    the holders are cleared and the function returns ``False``.

    The probe is the cheapest possible call into the hardware layer
    (``stat.poll()``). If the process is down the ``poll()`` raises
    immediately on the real ``linuxcnc`` module, while the mock
    always succeeds. This is the contract relied on by the retry
    loop.
    """
    global _machine_stat, _machine_cmd, _machine_error
    try:
        new_stat = linuxcnc.stat()
        new_cmd = linuxcnc.command()
        new_error = linuxcnc.error_channel()
        # Probe the binding with the cheapest available call. On
        # the real ``linuxcnc`` module this raises if the NML
        # socket is unreachable; on the mock it always succeeds.
        new_stat.poll()
    except Exception as exc:  # noqa: BLE001 - defensive
        logger.warning("LinuxCNC bind failed: %s", exc)
        _machine_stat = None
        _machine_cmd = None
        _machine_error = None
        return False
    _machine_stat = new_stat
    _machine_cmd = new_cmd
    _machine_error = new_error
    return True


def try_reconnect() -> bool:
    """Try to reconnect to LinuxCNC if we are currently disconnected.

    Returns ``True`` if the state is now ``READY`` (either it was
    already ``READY`` or the bind succeeded on this call). Returns
    ``False`` if the bind failed and we remain in
    ``LINUXCNC_DISCONNECTED``. The function is a no-op when the
    state is already ``READY`` — the retry loop still re-probes
    the live connection so a dead LinuxCNC process is detected.
    """
    if _try_bind():
        _set_state(ConnectionState.READY)
        return True
    _set_state(ConnectionState.LINUXCNC_DISCONNECTED)
    return False


# Initial bind attempt. If the LinuxCNC process is not running the
# real ``linuxcnc.stat()`` raises; ``_try_bind`` swallows it and
# leaves the state as ``LINUXCNC_DISCONNECTED`` so the backend can
# still boot. The retry loop in :func:`connection_retry_loop`
# (started by the FastAPI lifespan) will reconnect automatically.
if _try_bind():
    _set_state(ConnectionState.READY)
else:
    _set_state(ConnectionState.LINUXCNC_DISCONNECTED)


async def connection_retry_loop(
    interval_sec: float = 5.0,
    sleep_fn: Callable[[float], "asyncio.Future[float]"] = asyncio.sleep,
) -> None:
    """Periodically retry the LinuxCNC bind.

    The loop runs until cancelled. On every tick it:

    1. Probes the live connection if the state is ``READY`` (a
       LinuxCNC process can shut down between two ticks, so a
       previously-healthy ``stat`` may now raise).
    2. Attempts to bind if the state is ``LINUXCNC_DISCONNECTED``.

    The interval defaults to 5 s — short enough to feel responsive
    after LinuxCNC starts, long enough that a misconfigured
    controller does not flood the log. Tests can override
    ``sleep_fn`` to avoid real ``asyncio.sleep`` calls.
    """
    logger.info(
        "LinuxCNC connection retry loop running (interval=%.1fs)",
        interval_sec,
    )
    try:
        global _machine_stat, _machine_cmd, _machine_error
        while True:
            await sleep_fn(interval_sec)
            current = get_connection_state()
            if current == ConnectionState.READY:
                # Probe the live connection so a LinuxCNC shutdown
                # that happened between two ticks is detected.
                stat = _machine_stat
                if stat is None:
                    _set_state(ConnectionState.LINUXCNC_DISCONNECTED)
                    continue
                try:
                    stat.poll()
                except Exception as exc:  # noqa: BLE001 - defensive
                    logger.warning(
                        "LinuxCNC probe poll failed: %s; "
                        "transitioning to LINUXCNC_DISCONNECTED",
                        exc,
                    )
                    _machine_stat = None
                    _machine_cmd = None
                    _machine_error = None
                    _set_state(ConnectionState.LINUXCNC_DISCONNECTED)
                continue
            # Disconnected: attempt to reconnect.
            try:
                if _try_bind():
                    _set_state(ConnectionState.READY)
            except Exception as exc:  # noqa: BLE001 - defensive
                logger.error("Unexpected error in retry loop: %s", exc)
    except asyncio.CancelledError:
        logger.info("LinuxCNC connection retry loop cancelled")
        raise


# ---------------------------------------------------------------------- #
# Public API (preserved for back-compat)                                  #
# ---------------------------------------------------------------------- #


def set_machine_config(cfg) -> None:
    """Inject a parsed MachineConfig instance into the hardware layer.

    Call this from application startup so downstream hardware code may
    read configuration metadata (axes, heaters, steppers) if needed.
    """
    global machine_config
    machine_config = cfg
    try:
        logger.info(f"Machine configuration injected (path={getattr(cfg, 'config_path', 'unknown')})")
    except Exception:
        logger.info("Machine configuration injected")


def get_machine_stat():
    """Returns the global machine stat object, or ``None`` when disconnected."""
    return _machine_stat


def get_machine_cmd():
    """Returns the global machine command object, or ``None`` when disconnected."""
    return _machine_cmd


def get_machine_error():
    """Returns the global machine error channel object, or ``None`` when disconnected."""
    return _machine_error


def is_ready() -> bool:
    """Return ``True`` iff the LinuxCNC connection is currently ``READY``."""
    return get_connection_state() == ConnectionState.READY


def execute_sync_cmd(cmd_name: str, cmd_timeout: float = 0, *args) -> dict:
    """
    Executes a LinuxCNC command and optionally waits for it to complete.

    This synchronous function handles calling the physical LinuxCNC command
    bindings and waiting for completion statuses.

    Args:
        cmd_name: The string name of the command to execute (e.g., 'jog', 'mode').
        cmd_timeout: How long to wait for command completion in seconds.
        *args: Arguments to pass to the underlying command function.

    Returns:
        dict: A status dictionary containing success information.

    Raises:
        HTTPException: If the command fails, times out, is unimplemented,
            or the LinuxCNC binding is currently disconnected (503).
    """
    # Fail fast with a 503 when the binding is offline. Callers
    # (FastAPI routers) get an actionable error without waiting for
    # the underlying ``AttributeError`` or socket timeout.
    if get_connection_state() != ConnectionState.READY:
        raise HTTPException(
            status_code=503,
            detail="LinuxCNC is not currently connected",
        )
    if _machine_cmd is None:
        # Defensive: the state is READY but the holder is missing.
        # This can only happen if a race cleared the holder between
        # the state check and the access; surface a 503 rather than
        # an ``AttributeError``.
        raise HTTPException(
            status_code=503,
            detail="LinuxCNC command channel is not available",
        )
    try:
        func = getattr(_machine_cmd, cmd_name)
        func(*args)

        if cmd_timeout > 0:
            # wait_complete blocks until the command is processed by LinuxCNC
            ret = _machine_cmd.wait_complete(cmd_timeout)
            if ret == getattr(linuxcnc, 'RCS_DONE', 1):
                return {"status": "success"}
            elif ret == getattr(linuxcnc, 'RCS_ERROR', 3):
                raise HTTPException(status_code=400, detail="Command execution error")
            else:
                raise HTTPException(status_code=408, detail="Command timed out")
        else:
            return {"status": "success"}
    except AttributeError:
        raise HTTPException(
            status_code=500,
            detail=f"Command '{cmd_name}' not implemented in hardware interface."
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Command execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class Connection:
    """Thin object-oriented wrapper exposing the hardware interface.

    This mirrors the module-level helper functions so other code can
    import a singleton :data:`connection` object. The new methods
    :meth:`get_state` and :meth:`try_reconnect` give callers a
    object-oriented way to query the lifecycle of the LinuxCNC
    binding added by issue #104.
    """

    def get_state(self) -> ConnectionState:
        return get_connection_state()

    def is_ready(self) -> bool:
        return is_ready()

    def try_reconnect(self) -> bool:
        return try_reconnect()

    def set_machine_config(self, cfg) -> None:
        return set_machine_config(cfg)

    def get_machine_stat(self):
        return get_machine_stat()

    def get_machine_cmd(self):
        return get_machine_cmd()

    def get_machine_error(self):
        return get_machine_error()

    def execute_sync_cmd(self, cmd_name: str, cmd_timeout: float = 0, *args) -> dict:
        return execute_sync_cmd(cmd_name, cmd_timeout, *args)


# Export a module-level singleton named ``connection`` for imports.
connection = Connection()
