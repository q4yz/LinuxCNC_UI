"""Hardware connection layer — LinuxCNC NML channel wrapper.

The connection module used to call ``linuxcnc.stat()`` /
``linuxcnc.command()`` / ``linuxcnc.error_channel()`` at import
time. Those constructors open NML channels to a running LinuxCNC
instance (status / command / error channels — see
``.agent/doc/linuxcnc_docs.htlm``). On a system where the real
``linuxcnc`` package is installed but LinuxCNC itself isn't
running yet, the constructors raise ``linuxcnc.error`` and the
backend crashes before FastAPI can boot.

The fix replaces the eager singletons with three
:class:`_LazyChannel` wrappers that:

* try the constructor on first call;
* cache the result on success and reuse it for every subsequent
  call (the historical contract);
* on failure (any exception, typically ``linuxcnc.error``) log a
  warning, cache the timestamp, return ``None``, and rate-limit
  retries with exponential backoff (1 s → 30 s).

The HTTP / WebSocket layers already tolerate ``None`` returns via
``getattr(machine_stat, 'attr', default)``; :func:`execute_sync_cmd`
translates a missing channel into ``HTTPException(503)`` so the
frontend gets a clear "LinuxCNC not running" signal instead of the
backend vanishing.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

from fastapi import HTTPException

logger = logging.getLogger("backend.hardware.connection")

# ---------------------------------------------------------------------------
# Module selection: real linuxcnc vs. mock fallback
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


# ---------------------------------------------------------------------------
# Lazy channel wrapper
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


# ---------------------------------------------------------------------------
# Module-level channel singletons
# ---------------------------------------------------------------------------

_stat_ch = _LazyChannel("stat")
_cmd_ch = _LazyChannel("command")
_error_ch = _LazyChannel("error_channel")


# ---------------------------------------------------------------------------
# Public API (preserves the historical function signatures)
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
# Optional machine-config injection
# ---------------------------------------------------------------------------

# Optional injected MachineConfig instance (set during FastAPI startup)
machine_config = None


def set_machine_config(cfg) -> None:
    """Inject a parsed MachineConfig instance into the hardware layer.

    Call this from application startup so downstream hardware code may
    read configuration metadata (axes, heaters, steppers) if needed.
    """
    global machine_config
    machine_config = cfg
    try:
        logger.info(
            f"Machine configuration injected (path={getattr(cfg, 'config_path', 'unknown')})"
        )
    except Exception:
        logger.info("Machine configuration injected")


# ---------------------------------------------------------------------------
# Connection facade
# ---------------------------------------------------------------------------


class Connection:
    """Thin wrapper exposing the hardware interface as an object.

    Mirrors the module-level helpers so legacy callers that imported
    the ``connection`` singleton keep working.
    """

    def set_machine_config(self, cfg) -> None:
        return set_machine_config(cfg)

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


# Module-level singleton for callers that prefer the object form.
connection = Connection()


__all__ = [
    "USE_MOCK",
    "linuxcnc",
    "get_machine_stat",
    "get_machine_cmd",
    "get_machine_error",
    "is_linuxcnc_connected",
    "execute_sync_cmd",
    "set_machine_config",
    "Connection",
    "connection",
]
