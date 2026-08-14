"""Regression tests for the offline / no-LinuxCNC paths in the
WebSocket telemetry layer.

The backend must boot and serve its telemetry endpoint even when
the LinuxCNC daemon isn't reachable. ``hardware.connection`` wraps
the NML channels in :class:`_LazyChannel`, so the channel helpers
return ``None`` until the daemon comes online. These tests pin the
contract that:

* ``get_current_state()`` returns the safe offline snapshot
  (``task_state=ESTOP``, ``estop=1``) when the channel is offline,
* :func:`telemetry_loop` survives a tick where the channel helpers
  return ``None`` instead of crashing with ``AttributeError`` every
  100 ms,
* :func:`websocket_telemetry` accepts a connection, sends the
  offline snapshot, and removes itself from
  ``manager.active_connections`` on **any** exception — not only
  ``WebSocketDisconnect``.

The previous implementation eagerly captured
``machine_stat = get_machine_stat()`` at the top of the loop and
called ``.poll()`` on it directly. When ``linuxcnc`` was installed
but the daemon wasn't running, ``get_machine_stat()`` returned
``None`` and the loop spammed ``Error in telemetry loop: 'NoneType'
object has no attribute 'poll'`` every tick until the daemon came
online. The handler had the same bug plus leaked connections in
``active_connections`` because ``manager.disconnect()`` only ran
inside the ``WebSocketDisconnect`` branch.

These tests run via ``node --test`` style source-text regex on the
fixed source plus the behavioural tests below.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi import WebSocketDisconnect


async def _drive_one_tick():
    """Run :func:`telemetry_loop` until the first ``await asyncio.sleep(0.1)``.

    The loop sleeps 100 ms every iteration. We patch the sleep to
    a no-op then cancel the wrapping task after one round so the
    real test only pays for one cycle.
    """
    from routers import servo_thread as ws_mod

    real_sleep = asyncio.sleep

    async def fake_sleep(_seconds):
        # Yield exactly once so the loop reaches its tail-sleep
        # and the wrapped task can be cancelled cleanly.
        await real_sleep(0)

    with patch.object(asyncio, "sleep", side_effect=fake_sleep):
        task = asyncio.create_task(ws_mod.telemetry_loop())
        # Let the loop cycle once.
        await real_sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def test_get_current_state_returns_offline_snapshot_when_channels_offline():
    """``get_current_state()`` must return the ESTOP snapshot when
    the NML channel is offline.

    The operator-facing UI relies on this to render the red "Estop"
    badge rather than a stale frame when LinuxCNC is unreachable.
    """
    from routers import servo_thread as ws_mod

    with patch.object(ws_mod, "get_machine_stat", return_value=None):
        snapshot = ws_mod.get_current_state()

    assert snapshot["task_state"] == 1  # STATE_ESTOP
    assert snapshot["estop"] == 1
    # Position arrays must be present so the frontend's destructuring
    # of ``full_state`` payloads stays stable across the offline /
    # online boundary.
    assert snapshot["position"] == [0.0] * 9
    assert snapshot["actual_position"] == [0.0] * 9
    assert snapshot["relative_position"] == [0.0] * 9
    assert snapshot["file"] == ""
    assert snapshot["interp_state"] == 1  # INTERP_IDLE
    # Sensors moved to the base-thread snapshot. The 10 Hz
    # WebSocket stream no longer carries them so the dashboard
    # cannot accidentally double-fetch via a stale ``full_state``.
    assert "temperatures" not in snapshot


def test_telemetry_loop_survives_one_offline_tick():
    """One iteration of ``telemetry_loop`` with both channel
    helpers returning ``None`` must not raise ``AttributeError``.

    Before the fix the loop called ``machine_stat.poll()``
    directly; the offline case ``get_machine_stat() is None``
    crashed with ``AttributeError`` every 100 ms. The new
    implementation re-fetches inside the body and skips the
    ``.poll()`` call when either channel is offline.
    """
    from routers import servo_thread as ws_mod

    with patch.object(ws_mod, "get_machine_stat", return_value=None), \
         patch.object(ws_mod, "get_machine_error", return_value=None):
        # Drive exactly one tick of the loop. If the bug is
        # present, an ``AttributeError`` is raised the moment
        # the loop body touches ``None.poll()`` and propagates
        # out of the wrapped task despite the outer
        # ``try/except`` (the inner ``except`` swallows it but
        # we still observe the noisy log message every tick;
        # for this test we care that no exception escapes).
        asyncio.run(_drive_one_tick())


def test_telemetry_loop_survives_transient_poll_oserror(caplog):
    """A single transient ``stat.poll()`` OSError must not crash the loop
    and must be logged at DEBUG, not ERROR.

    The cpython linuxcnc bindings surface the C-level NML "buffer
    empty" condition as ``poll()`` returning ``-1`` *without* raising
    a Python exception; ctypes then logs ``error return without
    exception set`` the next time an exception is raised anywhere on
    the same thread. LinuxCNC's startup race window (NML channel
    opened before the task is ready) produces this every 100 ms.

    The fix wraps each ``poll()`` in its own try/except and treats
    the failure as a transient state — skip this tick, sleep, retry.
    Without the local handler, the outer ``except Exception`` catches
    it and logs at ERROR every tick, spamming the operator log.
    """
    from routers import servo_thread as ws_mod

    class _FlakyStat:
        """A ``stat`` channel whose first ``poll()`` raises OSError.

        Subsequent polls succeed so the loop can move past the
        transient failure and reach a clean exit on cancellation.
        """

        def __init__(self):
            self.poll_calls = 0

        def poll(self):
            self.poll_calls += 1
            if self.poll_calls == 1:
                raise OSError("synthetic stat.poll() failure")
            return None

        # ``get_current_state`` reads a handful of tuple-shaped and
        # int-shaped attributes; the stubs below mirror that shape.
        actual_position = (0.0,) * 9
        position = (0.0,) * 9
        g5x_offset = (0.0,) * 9
        g92_offset = (0.0,) * 9
        tool_offset = (0.0,) * 9
        task_state = 1
        estop = 1
        task_mode = 1
        state = 1
        file = ""
        homed = [0, 0, 0]
        interp_state = 1
        g5x_index = 1

    class _EmptyError:
        def poll(self):
            return None

        errors = []

    flaky = _FlakyStat()
    empty = _EmptyError()

    with patch.object(ws_mod, "get_machine_stat", return_value=flaky), \
         patch.object(ws_mod, "get_machine_error", return_value=empty), \
         patch.object(ws_mod.manager, "active_connections", new=[]), \
         caplog.at_level("DEBUG", logger="backend.routers.servo_thread"):
        # Drive three ticks: first one hits the OSError, the next two
        # succeed. If the bug is present, the loop dies on tick 1
        # OR the outer except logs at ERROR.
        async def drive():
            real_sleep = asyncio.sleep

            async def fake_sleep(_s):
                await real_sleep(0)

            with patch.object(asyncio, "sleep", side_effect=fake_sleep):
                task = asyncio.create_task(ws_mod.telemetry_loop())
                # Yield enough times for ~3 ticks.
                for _ in range(3):
                    await real_sleep(0)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        asyncio.run(drive())

    # The transient failure was handled locally — no ERROR-level log.
    error_records = [
        r for r in caplog.records if r.levelname == "ERROR"
        and "telemetry_loop" in r.message
    ]
    assert error_records == [], (
        f"transient stat.poll() OSError leaked to the outer handler "
        f"and produced ERROR logs: {[r.message for r in error_records]}"
    )

    # The loop continued past the failure — flaky.poll() was called
    # at least twice.
    assert flaky.poll_calls >= 2, (
        f"loop did not retry after the first poll() failure "
        f"(poll_calls={flaky.poll_calls})"
    )


def test_telemetry_loop_survives_transient_error_channel_poll_oserror(caplog):
    """A single transient ``error_channel.poll()`` OSError must not crash."""
    from routers import servo_thread as ws_mod

    class _HealthyStat:
        def poll(self):
            return None

        # ``get_current_state`` reads a handful of tuple-shaped and
        # int-shaped attributes; the stubs below mirror that shape.
        actual_position = (0.0,) * 9
        position = (0.0,) * 9
        g5x_offset = (0.0,) * 9
        g92_offset = (0.0,) * 9
        tool_offset = (0.0,) * 9
        task_state = 1
        estop = 1
        task_mode = 1
        state = 1
        file = ""
        homed = [0, 0, 0]
        interp_state = 1
        g5x_index = 1

    class _FlakyError:
        def __init__(self):
            self.poll_calls = 0

        def poll(self):
            self.poll_calls += 1
            if self.poll_calls == 1:
                raise OSError("synthetic error_channel.poll() failure")
            return None

        errors = []

    healthy = _HealthyStat()
    flaky = _FlakyError()

    with patch.object(ws_mod, "get_machine_stat", return_value=healthy), \
         patch.object(ws_mod, "get_machine_error", return_value=flaky), \
         patch.object(ws_mod.manager, "active_connections", new=[]), \
         caplog.at_level("DEBUG", logger="backend.routers.servo_thread"):
        async def drive():
            real_sleep = asyncio.sleep

            async def fake_sleep(_s):
                await real_sleep(0)

            with patch.object(asyncio, "sleep", side_effect=fake_sleep):
                task = asyncio.create_task(ws_mod.telemetry_loop())
                for _ in range(3):
                    await real_sleep(0)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        asyncio.run(drive())

    error_records = [
        r for r in caplog.records if r.levelname == "ERROR"
        and "telemetry_loop" in r.message
    ]
    assert error_records == []
    assert flaky.poll_calls >= 2


def test_websocket_telemetry_cleans_up_on_non_disconnect_exception():
    """The WebSocket handler must remove the connection from
    ``manager.active_connections`` on **any** exception — not just
    the ``WebSocketDisconnect`` branch.

    Without the generic ``except Exception`` cleanup path, a
    subscriber whose first frame raised an unexpected exception
    would leak its entry in ``active_connections`` for the rest
    of the backend's lifetime, slowly growing the list and
    wasting broadcast cycles.
    """
    from routers import servo_thread as ws_mod

    class FakeWS:
        """Stand-in for a real WebSocket that always raises on poll.

        Records accept / send_text / receive_text calls so the
        test can assert the handler walked the expected path
        through ``connect`` → ``send_text`` → exception →
        ``disconnect``.
        """

        def __init__(self):
            self.calls = []

        async def accept(self):
            self.calls.append("accept")

        async def send_text(self, payload):
            self.calls.append(f"send_text:{len(payload)}")

        async def receive_text(self):
            self.calls.append("receive_text")
            # Simulate an unexpected runtime error such as the
            # connection closing mid-frame.
            raise RuntimeError("simulated: socket died mid-frame")


    fake = FakeWS()
    active_before = len(ws_mod.manager.active_connections)

    async def runner():
        try:
            await ws_mod.websocket_telemetry(fake)
        except RuntimeError:
            # The handler should ``raise`` after disconnecting so
            # FastAPI's WebSocket stack can finalise the close.
            pass

    asyncio.run(runner())

    # The connection was added on accept, removed on the catch-all
    # exception path. Net effect: zero length change.
    assert len(ws_mod.manager.active_connections) == active_before
    # And the handler did pass through every expected step.
    assert fake.calls[0] == "accept"
    assert any(c.startswith("send_text:") for c in fake.calls)
    assert fake.calls[-1] == "receive_text"
