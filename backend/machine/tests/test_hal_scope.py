"""Debug tab: 1 Hz pin values and the oscilloscope sampler / WebSocket."""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import services.HalScopeService as scope_mod
from exceptions import BadRequestError
from services.HalScopeService import HalScopeService, ScopeSampler, scope_value


def test_scope_value_plots_bits_as_0_1_and_gaps_for_unreadable():
    assert scope_value(True) == 1.0
    assert scope_value(False) == 0.0
    assert scope_value(3) == 3.0
    assert scope_value(2.5) == 2.5
    assert scope_value(None) is None
    assert scope_value("TRUE") is None


def test_sampler_sends_timestamped_blocks_of_all_pins():
    frames: List[Dict[str, Any]] = []
    got = threading.Event()

    def emit(frame):
        frames.append(frame)
        if sum(len(f.get("t", [])) for f in frames) >= 20:
            got.set()

    def read(name):
        if name == "boom.pin":
            raise RuntimeError("unreadable")
        return {"a.bit": True, "b.float": 1.5}[name]

    sampler = ScopeSampler(["a.bit", "b.float", "boom.pin"], 200, emit, read)
    sampler.start()
    assert got.wait(5), "no samples arrived"
    sampler.stop()
    assert not sampler.running

    samples = [f for f in frames if f["type"] == "samples"]
    times = [t for f in samples for t in f["t"]]
    assert times == sorted(times), "timestamps are monotonic"
    for frame in samples:
        assert frame["pins"] == ["a.bit", "b.float", "boom.pin"]
        assert len(frame["v"]) == 3
        assert all(len(column) == len(frame["t"]) for column in frame["v"])
        assert set(frame["v"][0]) == {1.0}
        assert set(frame["v"][1]) == {1.5}
        assert set(frame["v"][2]) == {None}, "an unreadable pin is a gap, not a dead scope"


def test_service_validates_and_clamps():
    service = HalScopeService(read=lambda name: 0.0)
    with pytest.raises(BadRequestError):
        service.start_sampler([], 100, lambda f: None)
    with pytest.raises(BadRequestError):
        service.start_sampler([f"p.{i}" for i in range(scope_mod.MAX_SCOPE_PINS + 1)], 100, lambda f: None)
    with pytest.raises(BadRequestError):
        service.start_sampler(["bad name; rm -rf"], 100, lambda f: None)

    fast = service.start_sampler(["a.b", "a.b"], 99999, lambda f: None)
    slow = service.start_sampler(["a.b"], 0.1, lambda f: None)
    try:
        assert fast.pins == ["a.b"], "duplicates removed"
        assert fast.rate_hz == scope_mod.MAX_RATE_HZ
        assert slow.rate_hz == scope_mod.MIN_RATE_HZ
    finally:
        service.stop_all()
    assert not fast.running and not slow.running


def test_read_values_reports_unreadable_pins_as_null():
    def read(name):
        if name == "gone.pin":
            raise KeyError(name)
        return {"a.bit": False, "b.float": 2.0, "c.str": "x"}[name]

    values = HalScopeService(read=read).read_values(["a.bit", "b.float", "c.str", "gone.pin"])
    assert values == {"a.bit": False, "b.float": 2.0, "c.str": None, "gone.pin": None}


@pytest.fixture()
def client(monkeypatch):
    from routers import hal_scope

    t0 = time.monotonic()
    service = HalScopeService(read=lambda name: (time.monotonic() - t0) if name == "x.ramp" else True)
    monkeypatch.setattr(hal_scope, "get_hal_scope_service", lambda: service)
    app = FastAPI()
    app.include_router(hal_scope.router)
    with TestClient(app) as test_client:
        yield test_client
    service.stop_all()


def test_values_endpoint(client):
    response = client.post("/api/v1/hal/pins/values", json={"pins": ["a.bit"]})
    assert response.status_code == 200
    assert response.json()["values"] == {"a.bit": True}
    assert client.post("/api/v1/hal/pins/values", json={"pins": []}).status_code == 400


def test_scope_socket_configure_stream_and_errors(client):
    with client.websocket_connect("/ws/hal-scope") as ws:
        ws.send_json({"type": "configure", "pins": ["x.ramp", "a.bit"], "rate_hz": 100})
        assert ws.receive_json() == {"type": "config", "pins": ["x.ramp", "a.bit"], "rate_hz": 100.0}

        frame = ws.receive_json()
        assert frame["type"] == "samples"
        assert frame["pins"] == ["x.ramp", "a.bit"]
        assert frame["v"][1][0] == 1.0

        ws.send_json({"type": "configure", "pins": "not-a-list"})
        message = ws.receive_json()
        while message["type"] == "samples":
            message = ws.receive_json()
        assert message["type"] == "error"

        ws.send_json({"type": "bogus"})
        message = ws.receive_json()
        while message["type"] == "samples":
            message = ws.receive_json()
        assert message == {"type": "error", "message": "unknown message type 'bogus'"}
