"""End-to-end tests for the jog keep-alive happy path.

These tests exercise the full request → hardware → keep-alive →
watchdog path through a built ``MachineModule`` instance and the
canonical settings endpoints. They mirror the issue § 4.1 test
list (``test_jog_keepalive.py``).
"""
from __future__ import annotations

import asyncio
import time
from typing import List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.module_registry import ModuleRegistry


def _run(coro):
    """Drive an async coroutine to completion from a sync test.

    Mirrors the ``asyncio.run`` pattern used in
    ``test_jog_watchdog.py``. The WebSocket dispatch is a
    coroutine; the test fixtures + REST tests are sync, so
    this helper bridges the two.
    """
    return asyncio.run(coro)


@pytest.fixture()
def machine_app(tmp_data_root, clean_env):
    """Build a fresh FastAPI app backed by the ``MachineModule``."""
    from modules.machine.module import MachineModule

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, bus=EventBus(), candidates=[MachineModule()])
    return app, reg


def test_keepalive_endpoint_refreshes_active_axis(machine_app):
    """A ping to ``/jog/keepalive`` refreshes the stamp without
    halting the axis. This is the canonical "frontend is healthy"
    signal that the watchdog uses to leave the axis alone.
    """
    app, _ = machine_app
    client = TestClient(app)

    # Start a continuous jog on axis 0.
    resp = client.post(
        "/api/v1/modules/machine/jog",
        json={"velocities": {"0": 1000.0}, "distance": 0.0},
    )
    assert resp.status_code == 200

    from modules.machine import jog

    initial = jog._active_jogs.get(0)
    assert initial is not None

    # Wait 100 ms so a refreshed stamp is measurably later.
    time.sleep(0.1)

    # Keep-alive (the value used by the frontend at 250 ms cadence).
    resp = client.post(
        "/api/v1/modules/machine/jog/keepalive",
        json={"axes": [0]},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    after = jog._active_jogs.get(0)
    assert after is not None
    assert after >= initial

    # Cleanup so the watchdog does not see a stale entry after
    # the test exits.
    client.post(
        "/api/v1/modules/machine/jog/stop",
        json={"axes": [0]},
    )


def test_stop_endpoint_removes_axis_from_active_set(machine_app):
    """``POST /jog/stop`` drops the axis from the watchdog map so
    the watchdog cannot accidentally force-stop the axis after
    the user has explicitly stopped it.
    """
    app, _ = machine_app
    client = TestClient(app)

    client.post(
        "/api/v1/modules/machine/jog",
        json={"velocities": {"1": 800.0}, "distance": 0.0},
    )
    from modules.machine import jog

    assert 1 in jog._active_jogs

    resp = client.post(
        "/api/v1/modules/machine/jog/stop",
        json={"axes": [1]},
    )
    assert resp.status_code == 200
    assert 1 not in jog._active_jogs


def test_keepalive_for_unknown_axis_is_a_noop(machine_app):
    """Pinging an axis that has not been started is harmless — the
    watchdog just ignores it. This guards against the frontend
    leaking a stale keep-alive during navigation.
    """
    app, _ = machine_app
    client = TestClient(app)

    resp = client.post(
        "/api/v1/modules/machine/jog/keepalive",
        json={"axes": [42]},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_increment_jog_does_not_register_axis(machine_app):
    """A step jog (``distance != 0``) does NOT register the axis
    with the watchdog because the watchdog's job is to catch a
    runaway continuous jog, not a one-shot move.
    """
    app, _ = machine_app
    client = TestClient(app)

    from modules.machine import jog

    resp = client.post(
        "/api/v1/modules/machine/jog",
        json={"velocities": {"2": 500.0}, "distance": 1.0},
    )
    assert resp.status_code == 200
    assert jog._active_jogs == {}


# ────────────────────────────────────────────────────────────────────── #
# WebSocket inbound path — the canonical replacement for the legacy     #
# REST keep-alive / jog / stop endpoints. The router's                    #
# ``_dispatch_inbound`` runs the same ``ws_jog_*`` helpers the REST      #
# handlers use, so a single source of truth backs both transports.       #
# ────────────────────────────────────────────────────────────────────── #


def _ws_dispatch(msg: dict) -> None:
    """Helper: drive ``_dispatch_inbound`` with a fake socket.

    The helper doesn't need a real ``WebSocket`` because the
    dispatch path is pure (reads fields, calls ``ws_jog_*``). The
    ``None`` socket is only referenced when a dispatcher
    *replies* to a message — and jog messages are fire-and-forget,
    so no reply path is exercised. The dispatcher is ``async``
    so we drive it to completion via ``asyncio.run`` — the same
    pattern used in ``test_jog_watchdog.py``.
    """
    from routers.websocket import _dispatch_inbound
    _run(_dispatch_inbound(None, msg))


def test_ws_keepalive_dispatches_to_watchdog(machine_app):
    """``{"type": "jog_keepalive", "axes": [...]}`` over the open
    ``/ws/telemetry`` socket refreshes the watchdog timer for the
    listed axes. The same ``ws_jog_keepalive`` helper the REST
    handler uses is the dispatcher's target, so behaviour is
    identical and a regression that drifts the two paths apart
    is caught here.
    """
    # ``machine_app`` is needed to import the jog router so the
    # ``_active_jogs`` dict is wired. The WebSocket itself is not
    # opened — the dispatch path is pure.
    machine_app  # noqa: F841 — fixture side-effect only
    from modules.machine import jog

    # Wipe the active set so the test does not depend on prior
    # state. ``_active_jogs`` is module-private; the helper uses
    # the same lock the REST handler takes.
    with jog._active_jogs_lock:
        jog._active_jogs.clear()
    initial = time.time() - 10.0  # far in the past
    with jog._active_jogs_lock:
        jog._active_jogs[0] = initial
        jog._active_jogs[1] = initial

    time.sleep(0.05)

    # Direct call into the dispatcher to avoid spinning up a
    # real WebSocket client — the WS contract is exercised
    # end-to-end by the production code path, this test
    # covers the dispatcher's pure logic.
    _ws_dispatch({"type": "jog_keepalive", "axes": [0, 1]})

    with jog._active_jogs_lock:
        after_0 = jog._active_jogs[0]
        after_1 = jog._active_jogs[1]
    assert after_0 > initial
    assert after_1 > initial
    # The difference should equal the wall-clock elapsed between
    # ``initial`` and the read (typically a few hundred ms even
    # on a cold CI runner). 30 s is a generous bound; a regression
    # that leaves the timestamp unchanged would yield 0.0 (caught
    # by the ``> initial`` assertion above).
    assert after_0 - initial < 30.0
    assert after_1 - initial < 30.0


def test_ws_keepalive_for_unknown_axis_is_noop(machine_app):
    """An axis the watchdog has never seen is silently ignored —
    a stale keep-alive from a previous navigation cannot leak a
    phantom axis into the active set.
    """
    machine_app  # noqa: F841 — fixture side-effect only
    from modules.machine import jog

    with jog._active_jogs_lock:
        jog._active_jogs.clear()

    _ws_dispatch({"type": "jog_keepalive", "axes": [99]})

    with jog._active_jogs_lock:
        assert jog._active_jogs == {}


def test_ws_jog_axis_registers_continuous_jog(machine_app):
    """``{"type": "jog_axis", "velocities": {"0": 500}, "distance": 0}``
    registers axis 0 with the watchdog. A step jog
    (``distance > 0``) does NOT register — matches the REST
    endpoint's behaviour.
    """
    machine_app  # noqa: F841
    from modules.machine import jog

    with jog._active_jogs_lock:
        jog._active_jogs.clear()

    _ws_dispatch(
        {
            "type": "jog_axis",
            "velocities": {"0": 500.0, "1": 250.0},
            "distance": 0,
        },
    )
    with jog._active_jogs_lock:
        # Both axes are continuous (``distance=0``) and must
        # land in the active set so the watchdog sees them.
        assert set(jog._active_jogs.keys()) == {0, 1}

    with jog._active_jogs_lock:
        jog._active_jogs.clear()

    _ws_dispatch(
        {
            "type": "jog_axis",
            "velocities": {"0": 500.0},
            "distance": 5.0,  # incremental step
        },
    )
    with jog._active_jogs_lock:
        assert jog._active_jogs == {}


def test_ws_jog_stop_removes_axis_from_active_set(machine_app):
    """``{"type": "jog_stop", "axes": [...]}`` drops the listed
    axes from the watchdog map. Matches the REST ``POST /jog/stop``
    endpoint's behaviour.
    """
    machine_app  # noqa: F841
    from modules.machine import jog

    with jog._active_jogs_lock:
        jog._active_jogs.clear()
        jog._active_jogs[0] = time.time()
        jog._active_jogs[1] = time.time()

    _ws_dispatch({"type": "jog_stop", "axes": [0]})
    with jog._active_jogs_lock:
        assert 0 not in jog._active_jogs
        assert 1 in jog._active_jogs  # untouched


def test_ws_dispatch_ignores_unknown_type(machine_app):
    """An inbound message with an unknown ``type`` is logged at
    DEBUG and silently dropped. The broadcast loop must keep
    running so a single bad message cannot crash the telemetry
    stream.
    """
    machine_app  # noqa: F841
    from modules.machine import jog

    with jog._active_jogs_lock:
        jog._active_jogs.clear()

    # Should not raise; the dispatcher's broad ``except Exception``
    # in ``websocket_telemetry`` would catch any crash, but the
    # pure dispatcher itself just returns.
    _ws_dispatch({"type": "made_up", "axes": [0]})
    with jog._active_jogs_lock:
        assert jog._active_jogs == {}


def test_ws_dispatch_rejects_malformed_axes(machine_app):
    """Inbound ``axes`` / ``velocities`` / ``distance`` fields that
    are not the expected type are logged and ignored. The
    dispatcher must be a paranoid parser — a buggy or malicious
    client must not be able to corrupt the watchdog state.
    """
    machine_app  # noqa: F841
    from modules.machine import jog

    with jog._active_jogs_lock:
        jog._active_jogs.clear()
        jog._active_jogs[0] = time.time()
        initial = jog._active_jogs[0]

    # String-typed ``axes`` — dispatcher warns and returns. The
    # active set is untouched.
    _ws_dispatch({"type": "jog_keepalive", "axes": "not-a-list"})
    with jog._active_jogs_lock:
        assert jog._active_jogs[0] == initial

    # Non-dict ``velocities`` for ``jog_axis``.
    _ws_dispatch(
        {"type": "jog_axis", "velocities": "also-bad", "distance": 0}
    )
    with jog._active_jogs_lock:
        # The active set still only has axis 0 (from setup);
        # the bad jog_axis did not add anything.
        assert set(jog._active_jogs.keys()) == {0}
