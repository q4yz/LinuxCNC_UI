"""``LedService``: segment colours, Klipper INDEX, SET_LED in MDI / macros."""
from __future__ import annotations

import pytest

import services.LedService as module
from core.led_color import SetLed
from exceptions import BadRequestError, NotFoundError

LEDS = [{"id": "sb", "pin": "PD3", "chain_count": 3, "color_order": "GRBW",
         "segments": [[1, 1], [2, 2]], "initial": [0.0, 0.0, 1.0, 0.0]}]


class Pin:
    def __init__(self):
        self.value = 0.0

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value


class Config:
    def load_payload(self):
        return {"leds": LEDS}


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(module, "ReadWriteDynamicHalPin", type("P", (), {"__class_getitem__": classmethod(lambda c, t: lambda *a: Pin())}))
    s = module.LedService(config=Config())
    s.preload_hal_pins()
    return s


def _colors(service):
    return [(seg["red"], seg["green"], seg["blue"]) for seg in service.state()[0]["segments"]]


def test_initial(service):
    service.apply_initial()
    assert _colors(service) == [(0.0, 0.0, 1.0), (0.0, 0.0, 1.0)]


def test_whole_chain_and_index(service):
    service.set(SetLed(led="sb", red=1.0))
    assert _colors(service) == [(1.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    service.set(SetLed(led="sb", green=1.0, index=3))  # LED 3 is in segment 2-3
    assert _colors(service) == [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    assert service._pins["sb"][1].value == float(0x00FF00)


def test_errors(service):
    with pytest.raises(NotFoundError):
        service.set(SetLed(led="nope"))
    with pytest.raises(BadRequestError):
        service.set(SetLed(led="sb", index=4))
    with pytest.raises(BadRequestError):
        service.run_command("SET_LED RED=1")


def test_run_command(service):
    assert service.run_command("SET_LED LED=sb BLUE=1 INDEX=1")
    assert _colors(service)[0] == (0.0, 0.0, 1.0)
    assert not service.run_command("G0 X1")


def test_mdi_and_macro(service, monkeypatch):
    from services.MacroExecutionService import MacroExecutionService
    from services.StateService import StateService

    monkeypatch.setattr(module, "get_led_service", lambda: service)
    assert StateService._ui_command("SET_LED LED=sb RED=1")
    assert _colors(service)[1] == (1.0, 0.0, 0.0)
    assert MacroExecutionService._set_led("m", "SET_LED LED=sb GREEN=1")
    assert not MacroExecutionService._set_led("m", "SET_LED LED=sb RED=5")
