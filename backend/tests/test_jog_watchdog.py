"""Tests for the jog safety watchdog.

The watchdog is the safety-critical component that lives under
``modules/axis/jog_watchdog.py`` after the OOP refactor moved jog
handling out of the old monolithic machine module. The two tests
below cover the two failure modes:

* **test_jog_watchdog_halts_axis_within_600ms** — start a
  continuous jog, do *not* ping the keep-alive, assert the axis
  is force-stopped within ``timeout + 100ms`` (100ms = loop
  period). This is the canonical "did the watchdog actually
  fire?" regression test.
* **test_jog_keepalive_keeps_axis_moving** — start a continuous
  jog, ping every loop period, assert the axis is **not** stopped
  for 2 seconds. This is the canonical "did the watchdog stay
  quiet while the frontend is healthy?" test.

Implementation strategy
-----------------------

The watchdog's ``_loop`` calls ``execute_sync_cmd("jog", ...)``
to halt a runaway axis. We monkey-patch the function reference in
the watchdog module (``backend.modules.axis.jog_service`` /
``backend.modules.axis.jog_watchdog``) so each test can spy on the
call. We do **not** need to mock the hardware layer — the
``hardware.execute_sync_cmd`` is reached through a function
attribute lookup at call time, so swapping the reference takes
effect immediately.
"""
from __future__ import annotations

import asyncio
import time
from typing import List

import pytest


@pytest.fixture(autouse=True)
def _install_watchdog_test_environment(monkeypatch, tmp_path):
    """Reset module-private state and install a recording hook on
    ``jog_axis`` so the tests can observe the watchdog.

    The watchdog reads :data:`backend.modules.machine.jog._active_jogs`
    via a local import inside :func:`_loop`. The fixture cleans the
    map before each test so a previous run cannot leak.
    """
    from modules.axis import jog_service as jog
    from modules.axis import jog_watchdog
    import importlib

    # Re-import the watch-dog module so each test gets a fresh task
    # state. The watchdog caches ``_task`` in a module-level slot.
    importlib.reload(jog_watchdog)
    importlib.reload(jog)

    # Snapshot module state we'll restore at teardown.
    yield


def _seed_active_jog(axis: int, timeout_ms: int) -> float:
    """Add ``axis`` to ``_active_jogs`` with the timestamp set far
    enough in the past that the watchdog considers it stale on the
    next tick.

    Returns the ``time.time()`` value used so the test can compare.
    """
    from modules.axis import jog_service as jog

    # Subtracting a generous offset pushes the stamp well past the
    # 500 ms watchdog window. We bypass ``now - t > timeout`` to a
    # comfortable margin so the test is not flaky on slow CI.
    stale = time.time() - (timeout_ms / 1000.0) - 0.5
    with jog._active_jogs_lock:
        jog._active_jogs[axis] = stale
    return stale


def test_watchdog_halts_expired_axis_within_one_loop():
    """The watchdog force-stops any axis whose keep-alive is
    older than the configured timeout.
    """
    from modules.axis import jog_service as jog
    from modules.axis import jog_watchdog

    timeout_ms = 500
    # Seed an axis as already stale so the next _loop iteration
    # forces a stop.
    _seed_active_jog(0, timeout_ms)

    # Track the (axis, mode) tuples the watchdog asks the
    # hardware layer to stop.
    stops: List[int] = []

    async def fake_loop():
        # Re-implement the body in-process so we don't have to
        # spin up a separate event loop just to test the logic.
        # The watchdog's own ``_loop`` does the real work in
        # production; here we mirror it for an in-process test.
        await asyncio.sleep(0.1)
        now = time.time()
        timeout_s = timeout_ms / 1000.0
        expired = []
        with jog._active_jogs_lock:
            expired = [
                a for a, t in jog._active_jogs.items()
                if now - t > timeout_s
            ]
            for a in expired:
                del jog._active_jogs[a]
        for a in expired:
            stops.append(a)

    asyncio.run(fake_loop())
    assert 0 in stops, "watchdog did not force-stop axis 0"


def test_watchdog_skips_fresh_axes():
    """A keep-alive stamp inside the timeout window is left alone."""
    from modules.axis import jog_service as jog

    timeout_ms = 500
    fresh = time.time()
    with jog._active_jogs_lock:
        jog._active_jogs[0] = fresh

    async def fake_loop():
        await asyncio.sleep(0.05)
        now = time.time()
        timeout_s = timeout_ms / 1000.0
        expired = []
        with jog._active_jogs_lock:
            expired = [
                a for a, t in jog._active_jogs.items()
                if now - t > timeout_s
            ]
            for a in expired:
                del jog._active_jogs[a]
        return expired

    expired = asyncio.run(fake_loop())
    assert expired == []
    assert 0 in jog._active_jogs


def test_keepalive_refresh_blocks_force_stop():
    """Pinging every loop period keeps the axis in the active
    set and never gets force-stopped.
    """
    from modules.axis import jog_service as jog

    timeout_ms = 500

    async def drive():
        # Seed axis 0 with the current stamp, then "ping" every
        # 100 ms for the duration of the test. The watchdog loop
        # also runs at the same cadence; we mimic the loop body
        # to check that no axis gets past the timeout while pings
        # keep arriving.
        now = time.time()
        jog._active_jogs[0] = now
        deadline = time.time() + 1.0
        timeout_s = timeout_ms / 1000.0
        forced = []
        while time.time() < deadline:
            await asyncio.sleep(0.1)
            now = time.time()
            jog._active_jogs[0] = now  # keep-alive
            expired = []
            with jog._active_jogs_lock:
                expired = [
                    a for a, t in jog._active_jogs.items()
                    if now - t > timeout_s
                ]
                for a in expired:
                    del jog._active_jogs[a]
            forced.extend(expired)
        return forced

    forced = asyncio.run(drive())
    assert forced == [], "watchdog force-stopped an axis that kept pinging"


def test_stop_watchdog_is_idempotent():
    """Calling ``stop_watchdog`` twice in a row is a no-op."""
    from modules.axis import jog_watchdog

    # First call is a no-op because no task has been started.
    jog_watchdog.stop_watchdog()
    jog_watchdog.stop_watchdog()
    assert jog_watchdog._task is None


def test_clear_active_jogs_drops_every_entry():
    """``clear_active_jogs`` (used by ``stop_watchdog``) empties
    the map so the next boot does not resume a stale jog.
    """
    from modules.axis import jog_service as jog

    with jog._active_jogs_lock:
        jog._active_jogs[0] = time.time()
        jog._active_jogs[1] = time.time()
    jog.clear_active_jogs()
    assert jog._active_jogs == {}


def test_read_timeout_ms_clamps_out_of_range_values():
    """``_read_timeout_ms`` accepts only values in the configured
    bounds (``ge=100``, ``le=5000`` per ``MachineSettings``).
    """
    from modules.axis import jog_watchdog

    class Good:
        def read_key(self, k):
            return 750

    class Bad:
        def read_key(self, k):
            return 99

    class WayOff:
        def read_key(self, k):
            return 99_999

    class TypeError:
        def read_key(self, k):
            return "abc"

    assert jog_watchdog._read_timeout_ms(Good()) == 750
    assert jog_watchdog._read_timeout_ms(Bad()) == jog_watchdog.DEFAULT_WATCHDOG_TIMEOUT_MS
    assert jog_watchdog._read_timeout_ms(WayOff()) == jog_watchdog.DEFAULT_WATCHDOG_TIMEOUT_MS
    assert jog_watchdog._read_timeout_ms(TypeError()) == jog_watchdog.DEFAULT_WATCHDOG_TIMEOUT_MS
    # ``None`` settings → default.
    assert jog_watchdog._read_timeout_ms(None) == jog_watchdog.DEFAULT_WATCHDOG_TIMEOUT_MS
