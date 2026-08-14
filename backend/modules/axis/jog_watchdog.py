"""Background watchdog for continuous jog safety.

Pure logic — no hardware imports. Reads active-jog state from
:mod:`backend.modules.axis.jog_service` and force-stops expired
axes by calling :func:`backend.modules.axis.jog_service.stop_axis`.

Mirrors the historical 500 ms keep-alive window from the legacy
``backend/routers/jog.py``. The watchdog is started by
:meth:`backend.modules.axis.module.AxisModule.on_load` and
stopped by :meth:`backend.modules.axis.module.AxisModule.on_unload`.
Because the registry may invoke ``on_unload`` more than once
under ``uvicorn --reload``, :func:`start_watchdog` and
:func:`stop_watchdog` are idempotent.

Configuration
-------------

``WATCHDOG_TIMEOUT_MS`` is read from the persisted module
settings once at start time. Operators wanting to tune the
timeout must restart the backend — this is the documented v1
behaviour.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger("backend.modules.axis.jog_watchdog")


# Keep the historical constant available for callers and tests
# while allowing the module settings store to override it at task
# startup.
WATCHDOG_TIMEOUT_MS = 500
WATCHDOG_TIMEOUT_S = WATCHDOG_TIMEOUT_MS / 1000.0
DEFAULT_WATCHDOG_TIMEOUT_MS = WATCHDOG_TIMEOUT_MS


_task: "Optional[asyncio.Task]" = None
# Cached timeout. ``_task`` is reset by ``start_watchdog`` so the
# loop re-reads its settings on every restart, which is exactly
# the v1 contract.
_timeout_ms_cache: int = DEFAULT_WATCHDOG_TIMEOUT_MS


def _read_timeout_ms(settings_store) -> int:
    """Return the timeout configured in ``settings_store``.

    Tolerates missing keys, raised exceptions, and an unset store
    by falling back to :data:`DEFAULT_WATCHDOG_TIMEOUT_MS`.
    Operators who store a value outside the documented bounds
    (``ge=100``, ``le=5000`` per :class:`backend.modules.axis.settings.MachineSettings`)
    are clamped here.
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


async def _loop() -> None:
    """Body of the watchdog task.

    Wakes every 100 ms (``asyncio.sleep(0.1)``), asks
    :mod:`backend.modules.axis.jog_service` for the active-jog
    snapshot, and force-stops any axis whose last-ping stamp is
    older than the cached timeout. The hardware-stop dispatch is
    delegated to ``jog_service.stop_axis(axis)`` so this module
    never imports ``hardware``.

    Capped at 10 minutes (``MAX_LIFETIME_S``) so a leaked task
    does not run forever in degenerate test environments.
    """
    from .jog_service import (
        snapshot_active_jogs,
        stop_axis,
        _unregister_active_jog,
    )

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
        active = snapshot_active_jogs()
        expired = [
            axis for axis, t in active.items() if now - t > timeout_s
        ]
        for axis in expired:
            _unregister_active_jog(axis)
            logger.warning(
                "SAFETY WATCHDOG: missed keep-alive on axis %s — STOP",
                axis,
            )
            try:
                stop_axis(axis)
            except Exception:
                # Hardware layer is in a bad state — log and keep
                # going. The next tick will try again.
                logger.exception(
                    "Watchdog stop failed for axis %s", axis
                )


def start_watchdog(settings_store=None) -> None:
    """Spawn the watchdog asyncio task.

    Idempotent: a second call while the previous task is still
    running is a no-op. The ``settings_store`` argument is
    optional; when omitted the watchdog uses
    :data:`DEFAULT_WATCHDOG_TIMEOUT_MS`.
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
    """Cancel the watchdog task and reset module state.

    Idempotent. Clears :data:`backend.modules.axis.jog_service._active_jogs`
    so the next boot starts fresh — under ``uvicorn --reload`` the
    previous task may have left a stale entry behind, and reloading
    should not resume a jog the operator has explicitly cancelled.
    """
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
    # Clear any lingering state so the next boot does not resume a
    # jog whose keep-alive trail was lost when the task was torn down.
    try:
        from .jog_service import clear_active_jogs

        clear_active_jogs()
    except Exception:
        # If the module failed to import in the first place there is
        # nothing to clear.
        pass
    logger.info("Jog safety watchdog stopped.")


__all__ = [
    "start_watchdog",
    "stop_watchdog",
    "WATCHDOG_TIMEOUT_MS",
    "WATCHDOG_TIMEOUT_S",
    "DEFAULT_WATCHDOG_TIMEOUT_MS",
]
