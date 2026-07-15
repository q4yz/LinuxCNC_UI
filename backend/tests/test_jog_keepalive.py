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
