"""``GET /api/v1/hal/pins`` — every HAL pin with its value, read fresh.

Unlike the editor layout (cached on first build, so its values freeze),
this endpoint re-reads HAL on every call.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dtos.pins.HalPin import HalDirection
from dtos.pins.MachineHalPin import MachineHalPin


def _pin(comp: str, name: str, value: Any, direction: HalDirection = HalDirection.OUT) -> MachineHalPin[Any]:
    return MachineHalPin(component_name=comp, pin=name, value=value, direction=direction, description="")


def _client(monkeypatch, reads):
    from routers import hal as hal_router
    from services.HalPinSignalService import get_hal_pin_signal_service

    service = get_hal_pin_signal_service()
    calls = iter(reads)
    monkeypatch.setattr(service, "_read_pins_from_linuxcnc", lambda: next(calls))
    app = FastAPI()
    app.include_router(hal_router.router)
    return TestClient(app)


def test_pins_carry_their_current_value_and_type(monkeypatch):
    client = _client(monkeypatch, [[
        _pin("motion", "spindle-on", True),
        _pin("spindle.0", "speed-out", 1200.5),
        _pin("joint.0", "home-sw-in", False, HalDirection.IN),
    ]])
    body = client.get("/api/v1/hal/pins").json()
    by_name = {p["full_name"]: p for p in body["pins"]}

    assert by_name["motion.spindle-on"]["value"] is True
    assert by_name["motion.spindle-on"]["type"] == "bit"
    assert by_name["spindle.0.speed-out"]["value"] == 1200.5
    assert by_name["spindle.0.speed-out"]["type"] == "float"
    assert by_name["joint.0.home-sw-in"]["value"] is False
    assert by_name["joint.0.home-sw-in"]["direction"] == "in"
    assert body["read_at"].endswith("Z")


def test_every_call_reads_hal_again(monkeypatch):
    client = _client(monkeypatch, [[_pin("motion", "spindle-on", False)], [_pin("motion", "spindle-on", True)]])
    first = client.get("/api/v1/hal/pins").json()["pins"][0]["value"]
    second = client.get("/api/v1/hal/pins").json()["pins"][0]["value"]
    assert (first, second) == (False, True)
