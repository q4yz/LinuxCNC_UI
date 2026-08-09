"""Tests for the LinuxCNC connection state machine.

Issue #104 — Graceful degradation. These tests pin down the
behaviour added on top of :mod:`backend.hardware.connection`:

* The initial bind attempt does not raise: a failure is logged
  and the state flips to ``LINUXCNC_DISCONNECTED`` instead of
  taking the backend down.
* :func:`try_reconnect` flips the state back to ``READY`` once
  the underlying bind succeeds, and a state listener registered
  *before* the transition is invoked exactly once.
* :func:`execute_sync_cmd` raises a 503 when the binding is
  offline, so routers do not need to special-case the
  disconnected state.
* The background :func:`connection_retry_loop` promotes a
  disconnected binding to ``READY`` and surfaces a bind failure
  that happens after the initial bind (a LinuxCNC shutdown).
* The hardware-layer holder functions return ``None`` while the
  state is disconnected, so callers must handle the
  disconnected case explicitly rather than relying on the
  proxy objects being live.

The tests deliberately do **not** re-import :mod:`hardware.connection`
between tests. Module-level state is migrated into a couple of
helper fixtures that swap the holders in and out via the
``monkeypatch`` fixture so each test starts from a known state.
"""
from __future__ import annotations

import asyncio
import threading
from typing import List

import pytest

# Import the connection module directly through ``sys.modules`` so
# the locally-rebound ``connection`` singleton does not shadow the
# module path. The package's ``__init__`` re-exports the singleton
# under the same name, which would otherwise yield a ``Connection``
# instance instead of the module.
import importlib
import sys as _sys

import hardware.connection  # noqa: F401  (registers the module)
connection_module = _sys.modules["hardware.connection"]
from hardware.connection import (
    ConnectionState,
    Connection,
    add_state_listener,
    connection_retry_loop,
    execute_sync_cmd,
    get_connection_state,
    get_machine_stat,
    remove_state_listener,
)
from hardware.connection import connection as hardware_connection_singleton
from fastapi import HTTPException


# ---------------------------------------------------------------------- #
# Fixtures                                                               #
# ---------------------------------------------------------------------- #


@pytest.fixture()
def reset_state(monkeypatch):
    """Reset the connection state for each test.

    The state machine is module-level state, so the only safe way
    to give tests a clean slate is to mutate the held values via
    :func:`setattr` and the ``monkeypatch`` fixture. The fixture
    also unregisters any state listeners the previous test
    registered — the listener list is itself module-level. The
    teardown restores the mock module and the original state so
    the rest of the test suite is unaffected by these tests.
    """
    # Snapshot the pre-test state so the teardown can restore it.
    original_state = get_connection_state()
    original_stat = connection_module._machine_stat
    original_cmd = connection_module._machine_cmd
    original_error = connection_module._machine_error
    original_linuxcnc = connection_module.linuxcnc

    # Clear listeners and holders, then force a known starting
    # state. ``_set_state`` is the canonical writer that the
    # production code uses too.
    connection_module._state_listeners.clear()
    monkeypatch.setattr(connection_module, "_machine_stat", None, raising=False)
    monkeypatch.setattr(connection_module, "_machine_cmd", None, raising=False)
    monkeypatch.setattr(connection_module, "_machine_error", None, raising=False)
    connection_module._set_state(ConnectionState.LINUXCNC_DISCONNECTED)
    yield
    connection_module._state_listeners.clear()
    # Restore the production state so subsequent tests see the
    # the original (mock or real) bind outcome.
    monkeypatch.setattr(connection_module, "_machine_stat", original_stat, raising=False)
    monkeypatch.setattr(connection_module, "_machine_cmd", original_cmd, raising=False)
    monkeypatch.setattr(connection_module, "_machine_error", original_error, raising=False)
    monkeypatch.setattr(connection_module, "linuxcnc", original_linuxcnc, raising=False)
    connection_module._set_state(original_state)


# ---------------------------------------------------------------------- #
# State machine surface                                                   #
# ---------------------------------------------------------------------- #


def test_initial_state_is_disconnected_when_bind_fails(reset_state, monkeypatch):
    """A failing initial bind leaves the state in
    ``LINUXCNC_DISCONNECTED`` rather than raising.

    This is the canonical "LinuxCNC is not running at startup"
    case: importing the module must succeed so the FastAPI app
    can boot, and the operator must see a clear state instead
    of a stack trace.
    """

    class _BrokenLinuxCNC:
        @staticmethod
        def stat():
            raise RuntimeError("NML socket unreachable")

        @staticmethod
        def command():
            raise RuntimeError("NML socket unreachable")

        @staticmethod
        def error_channel():
            raise RuntimeError("NML socket unreachable")

    monkeypatch.setattr(connection_module, "linuxcnc", _BrokenLinuxCNC)

    # ``_try_bind`` is the only path that can promote the state.
    # The initial bind at import time is already done; we
    # exercise the path explicitly to prove the new behaviour.
    ok = connection_module._try_bind()
    assert ok is False
    assert get_connection_state() == ConnectionState.LINUXCNC_DISCONNECTED
    assert get_machine_stat() is None


def test_try_reconnect_promotes_to_ready(reset_state, monkeypatch):
    """``:func:`try_reconnect` flips the state to ``READY`` once
    the underlying bind succeeds.
    """

    class _FakeStat:
        def poll(self):
            return None

    class _WorkingLinuxCNC:
        @staticmethod
        def stat():
            return _FakeStat()

        @staticmethod
        def command():
            return object()

        @staticmethod
        def error_channel():
            return object()

    # Start from the disconnected state.
    assert get_connection_state() == ConnectionState.LINUXCNC_DISCONNECTED

    # Replace the linuxcnc module with a working stand-in and
    # try to reconnect.
    monkeypatch.setattr(connection_module, "linuxcnc", _WorkingLinuxCNC)
    promoted = connection_module.try_reconnect()
    assert promoted is True
    assert get_connection_state() == ConnectionState.READY
    assert get_machine_stat() is not None


def test_try_reconnect_stays_disconnected_on_failure(reset_state, monkeypatch):
    """``:func:`try_reconnect` keeps the state in
    ``LINUXCNC_DISCONNECTED`` when the bind raises.
    """

    class _BrokenLinuxCNC:
        @staticmethod
        def stat():
            raise RuntimeError("still down")

        @staticmethod
        def command():
            raise RuntimeError("still down")

        @staticmethod
        def error_channel():
            raise RuntimeError("still down")

    monkeypatch.setattr(connection_module, "linuxcnc", _BrokenLinuxCNC)
    promoted = connection_module.try_reconnect()
    assert promoted is False
    assert get_connection_state() == ConnectionState.LINUXCNC_DISCONNECTED


# ---------------------------------------------------------------------- #
# State listeners                                                         #
# ---------------------------------------------------------------------- #


def test_state_listener_is_invoked_on_transition(reset_state, monkeypatch):
    """A listener registered before the transition is invoked
    exactly once with the new state.
    """
    transitions: List[ConnectionState] = []

    def _on_change(new_state: ConnectionState) -> None:
        transitions.append(new_state)

    # The fixture already forced the state to ``LINUXCNC_DISCONNECTED``
    # before the listener was registered, so the listener sees only
    # subsequent transitions.
    add_state_listener(_on_change)
    try:
        connection_module._set_state(ConnectionState.READY)
        assert transitions == [ConnectionState.READY]

        # A no-op transition (state already ``READY``) must not
        # invoke the listener a second time.
        connection_module._set_state(ConnectionState.READY)
        assert transitions == [ConnectionState.READY]

        connection_module._set_state(ConnectionState.LINUXCNC_DISCONNECTED)
        assert transitions == [
            ConnectionState.READY,
            ConnectionState.LINUXCNC_DISCONNECTED,
        ]
    finally:
        remove_state_listener(_on_change)


def test_listener_is_not_invoked_when_state_unchanged(reset_state):
    """Setting the state to its current value is a no-op so the
    retry loop does not spam listeners on every tick.
    """
    events: List[ConnectionState] = []
    add_state_listener(lambda s: events.append(s))
    try:
        # The fixture put us in ``LINUXCNC_DISCONNECTED``; setting
        # it again must not invoke the listener.
        connection_module._set_state(ConnectionState.LINUXCNC_DISCONNECTED)
        assert events == []
    finally:
        remove_state_listener(events.append)


def test_listener_exception_is_swallowed(reset_state, caplog):
    """A buggy listener logging an exception is logged then
    swallowed so the retry loop keeps running.
    """
    def _buggy(_new_state: ConnectionState) -> None:
        raise RuntimeError("listener boom")

    add_state_listener(_buggy)
    try:
        # State must change (current != new) for the listener to fire.
        connection_module._set_state(ConnectionState.READY)
        # No exception propagated; the implementation logged it.
    finally:
        remove_state_listener(_buggy)


# ---------------------------------------------------------------------- #
# execute_sync_cmd behaviour                                              #
# ---------------------------------------------------------------------- #


def test_execute_sync_cmd_returns_503_when_disconnected(reset_state):
    """``execute_sync_cmd`` raises a 503 (not a generic 500) when
    the LinuxCNC binding is offline.
    """
    with pytest.raises(HTTPException) as exc_info:
        execute_sync_cmd("jog", 0, 0, 0)
    assert exc_info.value.status_code == 503
    assert "not currently connected" in exc_info.value.detail


def test_execute_sync_cmd_returns_503_when_holder_is_none(reset_state, monkeypatch):
    """Defensive: even with state ``READY``, a missing holder
    yields a 503 rather than an ``AttributeError``.
    """
    connection_module._set_state(ConnectionState.READY)
    monkeypatch.setattr(connection_module, "_machine_cmd", None, raising=False)
    with pytest.raises(HTTPException) as exc_info:
        execute_sync_cmd("jog", 0, 0, 0)
    assert exc_info.value.status_code == 503


def test_execute_sync_cmd_succeeds_when_ready(reset_state, monkeypatch):
    """A working state + holder returns ``{"status": "success"}``.
    """
    class _Sentinel:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            def _call(*args, **kwargs):
                self.calls.append((name, args, kwargs))
                return None

            return _call

    cmd = _Sentinel()
    connection_module._set_state(ConnectionState.READY)
    monkeypatch.setattr(connection_module, "_machine_cmd", cmd, raising=False)
    result = execute_sync_cmd("home", 0, 0)
    assert result == {"status": "success"}
    assert cmd.calls[0][0] == "home"


# ---------------------------------------------------------------------- #
# Connection wrapper                                                      #
# ---------------------------------------------------------------------- #


def test_connection_wrapper_exposes_state_helpers(reset_state):
    """The :class:`Connection` wrapper exposes the same surface
    as the module-level helpers.
    """
    assert isinstance(hardware_connection_singleton, Connection)
    assert hardware_connection_singleton.get_state() == ConnectionState.LINUXCNC_DISCONNECTED
    assert hardware_connection_singleton.is_ready() is False
    # ``try_reconnect`` against the disconnected state must
    # complete without raising and respect the current state.
    promoted = hardware_connection_singleton.try_reconnect()
    # The real ``linuxcnc`` module is the mock stand-in, so the
    # bind succeeds here and the state flips to ``READY``.
    assert promoted is True
    assert hardware_connection_singleton.is_ready() is True


# ---------------------------------------------------------------------- #
# connection_retry_loop                                                   #
# ---------------------------------------------------------------------- #


def test_retry_loop_promotes_disconnected_to_ready(reset_state, monkeypatch):
    """The retry loop flips the state to ``READY`` the first time
    the bind succeeds after a period of being disconnected.

    The loop is exercised with a fake ``asyncio.sleep`` so the
    test does not wait the full 5 s interval.
    """

    # The current linuxcnc module is the mock stand-in (the real
    # ``linuxcnc`` is not installed in CI). The mock's ``stat``
    # always succeeds, so as soon as the loop ticks once the
    # state must flip to ``READY``.
    sleep_calls: List[float] = []

    async def _fake_sleep(seconds: float):
        sleep_calls.append(seconds)
        # Cancel on the second tick so the loop terminates.
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError()

    async def _runner():
        try:
            await connection_retry_loop(interval_sec=0.01, sleep_fn=_fake_sleep)
        except asyncio.CancelledError:
            pass

    # ``asyncio.run`` owns a fresh event loop; everything inside
    # the ``_runner`` coroutine runs on it.
    asyncio.run(_runner())
    assert get_connection_state() == ConnectionState.READY


def test_retry_loop_detects_live_disconnect(reset_state, monkeypatch):
    """If the bound ``stat.poll()`` raises on a later tick, the
    loop flips the state back to ``LINUXCNC_DISCONNECTED``.
    """

    # A persistent holder that survives reconnects. The retry
    # loop must observe the disconnect on the next tick; if the
    # reconnect is then attempted against the same broken stat,
    # the bind must fail and the state remains
    # ``LINUXCNC_DISCONNECTED``.
    poll_count = {"n": 0}
    stat_instance = {"obj": None}

    class _FlakyStat:
        def poll(self):
            poll_count["n"] += 1
            if poll_count["n"] >= 2:
                raise RuntimeError("LinuxCNC shutdown")
            return None

    class _BrokenLinuxCNC:
        @staticmethod
        def stat():
            # Always return the same broken stat so a reconnect
            # cannot succeed.
            if stat_instance["obj"] is None:
                stat_instance["obj"] = _FlakyStat()
            return stat_instance["obj"]

        @staticmethod
        def command():
            return object()

        @staticmethod
        def error_channel():
            return object()

    monkeypatch.setattr(connection_module, "linuxcnc", _BrokenLinuxCNC)
    # Bring the connection to READY.
    assert connection_module.try_reconnect() is True
    assert get_connection_state() == ConnectionState.READY

    # Now run the retry loop for a few ticks. The second ``poll``
    # raises ``RuntimeError``; the loop must observe it and
    # flip the state to ``LINUXCNC_DISCONNECTED``.
    sleep_calls: List[float] = []

    async def _fake_sleep(seconds: float):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 3:
            raise asyncio.CancelledError()

    async def _runner():
        try:
            await connection_retry_loop(interval_sec=0.01, sleep_fn=_fake_sleep)
        except asyncio.CancelledError:
            pass

    asyncio.run(_runner())
    assert get_connection_state() == ConnectionState.LINUXCNC_DISCONNECTED


# ---------------------------------------------------------------------- #
# __init__ re-exports                                                     #
# ---------------------------------------------------------------------- #


def test_hardware_package_reexports_state_helpers():
    """The :mod:`hardware` package exposes the new helpers."""
    from hardware import (
        ConnectionState as CState,
        add_state_listener as add_l,
        get_connection_state as get_state,
        is_ready as ready,
        remove_state_listener as remove_l,
        try_reconnect as reconnect,
    )

    assert CState.READY.value == "READY"
    assert CState.LINUXCNC_DISCONNECTED.value == "LINUXCNC_DISCONNECTED"
    assert callable(get_state)
    assert callable(ready)
    assert callable(add_l)
    assert callable(remove_l)
    assert callable(reconnect)


# ---------------------------------------------------------------------- #
# WebSocket payload integration                                           #
# ---------------------------------------------------------------------- #


def test_websocket_full_state_includes_connection_state_field():
    """The full-state payload sent to a freshly-connected
    WebSocket client includes the new ``connection_state`` field.

    This is the same payload the frontend's telemetry handler
    consumes, so the field must be present and reflect the
    current state machine value.
    """
    from fastapi.testclient import TestClient

    # Import the websocket router directly so the test does not
    # need a full FastAPI app + lifespan — we only exercise the
    # WebSocket route in isolation.
    from routers.websocket import router as ws_router

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(ws_router)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/telemetry") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "full_state"
            data = msg["data"]
            assert "connection_state" in data
            assert data["connection_state"] in {
                ConnectionState.READY.value,
                ConnectionState.LINUXCNC_DISCONNECTED.value,
                ConnectionState.UNKNOWN.value,
            }


def test_websocket_full_state_sentinel_when_disconnected(monkeypatch):
    """When the binding is disconnected, the full-state payload
    uses the ESTOP-safe sentinel and surfaces the
    ``connection_state`` field.
    """
    from fastapi.testclient import TestClient

    from routers.websocket import router as ws_router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(ws_router)

    # Force the disconnected state *before* the WebSocket
    # connects. The ``monkeypatch`` fixture restores the original
    # state after the test.
    connection_module._set_state(ConnectionState.LINUXCNC_DISCONNECTED)
    monkeypatch.setattr(connection_module, "_machine_stat", None, raising=False)
    monkeypatch.setattr(connection_module, "_machine_cmd", None, raising=False)
    monkeypatch.setattr(connection_module, "_machine_error", None, raising=False)

    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws/telemetry") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "full_state"
                data = msg["data"]
                assert data["connection_state"] == "LINUXCNC_DISCONNECTED"
                # The sentinel payload biases toward ESTOP so the
                # UI never claims the machine is idle while we
                # have no real data.
                assert data["task_state"] == 1
                assert data["estop"] == 1
    finally:
        # The fixture's teardown restores the state, but be
        # explicit so the test is robust against reorder.
        connection_module._set_state(ConnectionState.READY)
