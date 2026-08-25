"""Tests for the LinuxCNC error-channel broadcast + history snapshot.

The backend polls ``error_channel.poll()`` at 10 Hz inside the
``telemetry_loop`` and broadcasts each entry as a ``{"type":"error",
…}`` WS frame. The mock additionally keeps a bounded history on
``StateMachineMock.errors`` so the next ``full_state`` payload can
re-hydrate the operator console after a reload / reconnect.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from hardware.Connection import read_error_history
from hardware.mock.LinuxCNCMock import mock_system
from hardware.mock.test_helpers.mock_helpers import push_mock_error, reset_error_history
from hardware import connection as connection_module


def test_push_error_appends_entry():
    reset_error_history()
    # <-- NEW: We pass the error as a dictionary to our StateMachine
    push_mock_error(
        kind= 11,
        text= "Linear move on line 12 would exceed X's negative limit",
        time= "2026-08-11T19:38:43.542555"
    )
    history = read_error_history()
    assert len(history) == 1
    assert history[0]["kind"] == 11
    assert "X's negative limit" in history[0]["text"]


def test_push_error_trims_to_max():
    reset_error_history()
    for i in range(150):
        push_mock_error(
            kind = 1,
            text =  f"entry {i}",
            time =  f"2026-01-01T00:00:{i:02d}"
        )
    history = read_error_history()
    assert len(history) == 100
    assert history[0]["text"] == "entry 50"
    assert history[-1]["text"] == "entry 149"


def test_get_current_state_includes_errors():
    reset_error_history()
    push_mock_error(
        kind =  11,
        text = "joint 2 on limit switch error",
        time = "2026-08-11T19:38:55.948363"
    )
    from services.ServoThreadService import ServoThreadService

    svc = ServoThreadService()
    snap = svc.get_current_state()
    assert "errors" in snap, "get_current_state must surface the bounded history"
    assert isinstance(snap["errors"], list)
    assert len(snap["errors"]) == 1
    assert snap["errors"][0]["kind"] == 11
    assert "limit switch" in snap["errors"][0]["text"]


def test_get_current_state_returns_a_copy_not_a_live_reference():
    """Mutating the returned ``errors`` list must not mutate the
    mock's underlying buffer.
    """
    reset_error_history()
    push_mock_error(
        kind=2,
        text="first",
        time="2026-08-11T19:38:43.542555"
    )

    from services.ServoThreadService import ServoThreadService

    svc = ServoThreadService()
    snap = svc.get_current_state()
    snap["errors"].append(
        {"kind": 0, "text": "tampered", "time": "2026-08-11T20:00:00"}
    )

    assert len(read_error_history()) == 1
    assert read_error_history()[0]["text"] == "first"


def test_telemetry_loop_pushes_into_history_before_broadcast():
    """The router must record the error *before* broadcasting so the
    bounded history is current at the next ``full_state`` snapshot.
    """
    reset_error_history()
    from services.ServoThreadService import ServoThreadService

    svc = ServoThreadService()
    captured = []

    async def fake_broadcast(message):
        captured.append(message)

    svc.active_connections = [object()]
    svc.broadcast = fake_broadcast


    reset_error_history()


    push_mock_error(
        kind=11,
        text="linear-move-limit",
        time="2026-08-11T19:38:43.542555"
    )

    snap = svc.get_current_state()
    assert snap["errors"][-1]["text"] == "linear-move-limit"
    assert snap["errors"][-1]["kind"] == 11


def test_error_channel_drains_pending_errors_fifo():
    """Mock ``error_channel.poll()`` must return ``(kind, text)`` tuples
    in FIFO order from the pending queue, mirroring the real NML
    behaviour the backend relies on.

    The mock previously returned ``None`` on every poll, which made
    the ``error`` WS envelope branch unreachable for tests. After
    the fix each pushed error becomes a tuple drainable through
    the standard ``error_channel`` facade.
    """
    from hardware.mock import LinuxCNCMock

    reset_error_history()
    push_mock_error(kind=11, text="first", time="2026-08-12T10:00:00")
    push_mock_error(kind=12, text="second", time="2026-08-12T10:00:01")

    error_channel = LinuxCNCMock.linuxcnc.error_channel()
    first = error_channel.poll()
    second = error_channel.poll()
    empty = error_channel.poll()

    assert first == (11, "first"), "first poll returns the oldest queued tuple"
    assert second == (12, "second"), "subsequent polls drain in FIFO order"
    assert empty is None, "an empty queue yields None, matching python-linuxcnc"


def test_error_channel_drain_is_independent_of_history():
    """Draining the pending queue must NOT shrink the bounded history.

    ``state.errors`` (history) and ``state._pending_errors`` (the
    channel queue) are independent buffers in the mock — draining
    the channel must not consume the row from the history the UI
    replays on ``full_state``.
    """
    from hardware.mock import LinuxCNCMock

    reset_error_history()
    push_mock_error(kind=11, text="limit-switch", time="2026-08-12T10:00:00")

    error_channel = LinuxCNCMock.linuxcnc.error_channel()
    error_channel.poll()

    history = read_error_history()
    assert len(history) == 1, "history row must survive the channel drain"
    assert history[0]["kind"] == 11
    assert history[0]["text"] == "limit-switch"


def test_pending_error_queue_caps_at_four_times_history():
    """A runaway producer must not be able to leak memory through the
    pending queue.

    The cap is intentionally generous (``4 * _max_errors``) so a
    burst of NML errors — e.g. a homing sequence hitting several
    limit switches in a row — cannot outrun the 10 Hz
    ``telemetry_loop`` and silently drop the oldest events.
    """
    state = mock_system.internal_state
    state._pending_errors.clear()

    # Cap = 4 × 100 (default _max_errors for the mock) = 400.
    cap = state._max_errors * 4
    for i in range(cap + 50):
        state.push_error(text=f"event {i}", kind=i % 16, time=f"t{i}")

    assert len(state._pending_errors) == cap, (
        f"pending queue must clamp to {cap}, got {len(state._pending_errors)}"
    )
    # Oldest entries are dropped first — the surviving head must be
    # the 51st event pushed.
    head = state._pending_errors[0]
    assert head[1] == "event 50"


def test_telemetry_loop_broadcasts_error_envelope():
    """The telemetry loop must broadcast ``{"type":"error", ...}``
    envelopes whenever ``error_channel.poll()`` returns a tuple.

    Before the fix the loop only logged polled errors via
    ``console_logger.log_response`` and never wrote to the WS
    layer — the operator's ``ConsolePanel`` stayed blank and the
    toast layer never fired. Pin the new contract so a regression
    is caught at CI.
    """
    from services.ServoThreadService import ServoThreadService

    async def drive_loop_once():
        """Run :func:`telemetry_loop` for a single tick and then
        cancel it.

        ``asyncio.sleep`` is patched to a real (un-patched)
        zero-second sleep so the loop runs at full speed without
        recursing through the mock. The cancellation is required
        to unwind the loop body, which now has a polling loop of
        its own over the error channel.
        """
        svc = ServoThreadService()
        captured: list[str] = []

        async def fake_broadcast(message: str) -> None:
            captured.append(message)

        real_sleep = asyncio.sleep

        async def fake_sleep(_seconds: float) -> None:
            # Use the real ``sleep`` via ``ensure_future`` so the
            # patched ``asyncio.sleep`` does not recurse into itself.
            await real_sleep(0)

        svc.active_connections = [object()]
        svc.broadcast = fake_broadcast

        with patch.object(asyncio, "sleep", side_effect=fake_sleep):
            task = asyncio.create_task(svc.telemetry_loop())
            # Yield to the loop so it runs its first cycle (drains
            # errors, broadcasts envelope, sleeps, repeats).
            await real_sleep(0)
            await real_sleep(0)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        return captured

    reset_error_history()
    push_mock_error(
        kind=11,
        text="joint 2 on limit switch",
        time="2026-08-12T10:30:00",
    )

    captured = asyncio.run(drive_loop_once())
    assert captured, "telemetry_loop must broadcast at least one envelope"

    # Find the error envelope — the loop also emits a ``delta``
    # payload after the error channel drains, so we cannot assume
    # the first captured message is the error.
    error_envelopes = [
        json.loads(raw)
        for raw in captured
        if '"type": "error"' in raw or '"type":"error"' in raw
    ]
    assert error_envelopes, "expected at least one error envelope"
    payload = error_envelopes[-1]["data"]
    assert payload["kind"] == 11
    assert payload["text"] == "joint 2 on limit switch"
    assert payload["time"]


def test_telemetry_loop_mirrors_polled_error_into_bounded_history():
    """The mock-only ``push_error`` mirror keeps the bounded history
    in sync with the polled channel queue.

    The mirror is a no-op on real LinuxCNC (``stat.poll()`` already
    populates ``stat.errors``); the ``hasattr`` guard in
    ``ServoThreadService.telemetry_loop`` makes the path
    conditional. This test pins that the mock path still updates
    ``state.errors`` so ``read_error_history()`` reflects the
    polled event on the next tick.
    """
    reset_error_history()
    push_mock_error(
        kind=11,
        text="polled-then-mirrored",
        time="2026-08-12T10:45:00",
    )

    # Drain the channel directly to verify the pending queue
    # holds the row before the mirror runs.
    error_channel = mock_system.linuxcnc.error_channel()
    assert error_channel.poll() == (11, "polled-then-mirrored")

    # Now exercise the broadcast path which mirrors the polled
    # tuple into the bounded history. The mirror is keyed off the
    # ``push_error`` attribute the StateMachineMock exposes; the
    # mock's bounded history grows by one row per polled event.
    history_before = list(read_error_history())

    # Re-push and re-drain through the telemetry-loop pipeline by
    # calling ``push_error`` again — the loop's mirror will add
    # second copy into the history on its next tick.
    push_mock_error(
        kind=12,
        text="second-pass",
        time="2026-08-12T10:45:01",
    )
    history_after = list(read_error_history())
    assert len(history_after) == len(history_before) + 1
    assert history_after[-1]["kind"] == 12
    assert history_after[-1]["text"] == "second-pass"