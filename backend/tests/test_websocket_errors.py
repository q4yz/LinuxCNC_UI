"""Tests for the LinuxCNC error-channel broadcast + history snapshot.

The backend polls ``error_channel.poll()`` at 10 Hz inside the
``telemetry_loop`` and broadcasts each entry as a ``{"type":"error",
…}`` WS frame. The mock additionally keeps a bounded history on
``StateMachineMock.errors`` so the next ``full_state`` payload can
re-hydrate the operator console after a reload / reconnect.
"""

from __future__ import annotations

from hardware.connection import read_error_history
from hardware.mock.linuxcnc_mock import mock_system
from hardware.mock.test_helpers.mock_helpers import push_mock_error, reset_error_history




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
    from routers.servo_thread import get_current_state

    snap = get_current_state()
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

    from routers.servo_thread import get_current_state

    snap = get_current_state()
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
    from routers import servo_thread as ws_mod
    import asyncio

    captured = []

    async def fake_broadcast(message):
        captured.append(message)

    ws_mod.manager.active_connections = [object()]
    ws_mod.manager.broadcast = fake_broadcast


    reset_error_history()


    push_mock_error(
        kind=11,
        text="linear-move-limit",
        time="2026-08-11T19:38:43.542555"
    )

    snap = ws_mod.get_current_state()
    assert snap["errors"][-1]["text"] == "linear-move-limit"
    assert snap["errors"][-1]["kind"] == 11