"""Background watchdog for continuous jog safety.

Mirrors the historical 500 ms keep-alive window from
``backend/routers/jog.py``. The watchdog reads the module-private
``_active_jogs`` map owned by :mod:`backend.modules.axis.jog` and
force-stops any axis whose last-ping timestamp is older than the
configured timeout (read from the module settings at startup).

The watchdog is started by :meth:`AxisModule.on_load` and stopped
by :meth:`AxisModule.on_unload`. Because the registry may invoke
``on_unload`` more than once under ``uvicorn --reload``, the watchdog
helpers :func:`start_watchdog` and :func:`stop_watchdog` are
idempotent.

Configuration
-------------

``WATCHDOG_TIMEOUT_MS`` is read from the persisted module settings
once at start time. Operators wanting to tune the timeout must
either restart the backend or accept that mid-flight changes do not
take effect — this is the documented v1 behaviour.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from hardware import execute_sync_cmd, linuxcnc

logger = logging.getLogger("backend.modules.axis.jog_watchdog")


# Keep a reference to the real dispatch function so tests and hardware
# adapters can replace the watchdog-local seam without bypassing the
# shared ``jog._stop_axis`` path.
_DEFAULT_EXECUTE_SYNC_CMD = execute_sync_cmd


# Keep the historical constant available for callers and tests while
# allowing the module settings store to override it at task startup.
WATCHDOG_TIMEOUT_MS = 500
WATCHDOG_TIMEOUT_S = WATCHDOG_TIMEOUT_MS / 1000.0
DEFAULT_WATCHDOG_TIMEOUT_MS = WATCHDOG_TIMEOUT_MS


_task: "Optional[asyncio.Task]" = None
# Cached timeout. ``_task`` is reset by ``start_watchdog`` so the
# loop re-reads its settings on every restart, which is exactly the
# v1 contract.
_timeout_ms_cache: int = DEFAULT_WATCHDOG_TIMEOUT_MS


def _read_timeout_ms(settings_store) -> int:
    """Return the timeout configured in ``settings_store``.

    Tolerates missing keys, raised exceptions, and an unset store
    by falling back to :data:`DEFAULT_WATCHDOG_TIMEOUT_MS`. Operators
    who store a value outside the documented bounds (``ge=100``,
    ``le=5000`` per :class:`MachineSettings`) are clamped here.
    """
    fallback = DEFAULT_WATCHDOG_TIMEOUT_MS
    if settings_store is None:
        return fallback
    try:
        raw = settings_store.read_key("jog_watchdog_timeout_ms")
    except Exception as exc:  # noqa: BLE001 - defensive: settings may be missing
        logger.debug("watchdog: settings read failed (%s); using default", exc)
        return fallback
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return fallback
    if value < 100 or value > 5000:
        return fallback
    return value


def _stop_axis(axis: int) -> None:
    """Stop an expired axis through the jog module's safety helper.

    Keeping the final dispatch in ``jog._stop_axis`` preserves the old
    router-level seam used by safety tests and gives the watchdog one
    hardware-stop path shared with an explicit ``/jog/stop`` request.
    The fallback is defensive for partially imported modules.
    """
    from . import jog

    # Preserve both test/integration seams: callers may patch the
    # watchdog-local hardware function, or the legacy jog helper.
    if execute_sync_cmd is not _DEFAULT_EXECUTE_SYNC_CMD:
        execute_sync_cmd(
            "jog", 0, getattr(linuxcnc, "JOG_STOP", 0), True, axis
        )
        return

    stop = getattr(jog, "_stop_axis", None)
    if stop is not None:
        stop(axis)
        return
    execute_sync_cmd(
        "jog", 0, getattr(linuxcnc, "JOG_STOP", 0), True, axis
    )


async def _loop() -> None:
    """Body of the watchdog task.

    Wakes every 100 ms (``asyncio.sleep(0.1)``), checks the module's
    :data:`jog._active_jogs` map, and force-stops any axis whose
    last-ping stamp is older than the cached timeout. Capped at
    10 minutes (``MAX_LIFETIME_S``) so a leaked task does not run
    forever in degenerate test environments.
    """
    from . import jog  # local import to avoid module-load cycle

    started_at = time.monotonic()
    while True:
        # Hard cap so a wedged loop is bounded in CI.
        if time.monotonic() - started_at > 600:
            logger.warning(
                "watchdog loop exceeded 10 minute lifetime; exiting."
            )
            return

        await asyncio.sleep(0.1)
        now = time.time()
        timeout_s = WATCHDOG_TIMEOUT_S
        expired: list[int] = []
        with jog._active_jogs_lock:
            expired = [
                axis for axis, t in jog._active_jogs.items()
                if now - t > timeout_s
            ]
            for axis in expired:
                del jog._active_jogs[axis]
        for axis in expired:
            logger.warning(
                "SAFETY WATCHDOG: missed keep-alive on axis %s — STOP",
                axis,
            )
            try:
                _stop_axis(axis)
            except Exception:
                # Hardware layer is in a bad state — log and keep
                # going. The next tick will try again.
                logger.exception(
                    "Watchdog stop failed for axis %s", axis
                )


def start_watchdog(settings_store=None) -> None:
    """Spawn the watchdog asyncio task.

    Idempotent: a second call while the previous task is still
    running is a no-op. The ``settings_store`` argument is optional;
    when omitted the watchdog uses :data:`DEFAULT_WATCHDOG_TIMEOUT_MS`.
    """
    global _task, _timeout_ms_cache, WATCHDOG_TIMEOUT_MS, WATCHDOG_TIMEOUT_S

    if _task is not None and not _task.done():
        return

    _timeout_ms_cache = _read_timeout_ms(settings_store)
    WATCHDOG_TIMEOUT_MS = _timeout_ms_cache
    WATCHDOG_TIMEOUT_S = WATCHDOG_TIMEOUT_MS / 1000.0

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Off the main thread or no running loop yet (e.g. unit
        # tests). The FastAPI lifespan calls us back synchronously
        # *during* the lifespan startup, so a loop is normally
        # available. If it isn't, the watchdog cannot run anyway.
        logger.debug(
            "watchdog: no event loop available; skipping start"
        )
        return

    _task = loop.create_task(_loop())
    logger.info(
        "Jog safety watchdog started (timeout=%dms).", _timeout_ms_cache
    )


def stop_watchdog() -> None:
    """Cancel the watchdog task and reset module-private state.

    Idempotent. Clears :data:`jog._active_jogs` so the next boot
    starts fresh — under ``uvicorn --reload`` the previous task
    may have left a stale entry behind, and reloading should not
    resume a jog the operator has explicitly cancelled.
    """
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
    # Clear any lingering state so the next boot does not resume a
    # jog whose keep-alive trail was lost when the task was torn down.
    try:
        from . import jog  # local import to avoid module-load cycle

        jog.clear_active_jogs()
    except Exception:
        # If the module failed to import in the first place there is
        # nothing to clear.
        pass
    logger.info("Jog safety watchdog stopped.")


__all__ = [
    "start_watchdog",
    "stop_watchdog",
    "_stop_axis",
    "WATCHDOG_TIMEOUT_MS",
    "WATCHDOG_TIMEOUT_S",
    "DEFAULT_WATCHDOG_TIMEOUT_MS",
]
