"""``IoService``: fans (%), ``[output_pin]`` toggles / PWM and ``[input_pin]``
states behind ``/api/v1/modules/io`` (`.agent/component/io_pins.md`)."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from exceptions import BadRequestError, NotFoundError, register_command_error_handler
from services import IoService as io_module
from services.IoService import IoService


class FakePin:
    def __init__(self, value: Any = 0) -> None:
        self.value = value

    def get_value(self) -> Any:
        return self.value

    def set_value(self, value: Any) -> None:
        self.value = value


@pytest.fixture()
def service(monkeypatch):
    fan = SimpleNamespace(id="fan", speed=FakePin(0.0))
    monkeypatch.setattr(io_module, "get_fans_service", lambda: SimpleNamespace(get_halpins=lambda: [fan]))
    io = IoService()
    io._outputs = {
        "case_light": ({"id": "case_light", "pwm": False, "value": 1}, FakePin(False)),
        "dimmable_light": ({"id": "dimmable_light", "pwm": True, "scale": 100, "value": 25}, FakePin(0.0)),
    }
    io._inputs = {"my_custom_button": FakePin(True)}
    io._preloaded = True
    return io, fan


def test_outputs_start_at_their_profile_value(service):
    io, _fan = service
    io.apply_start_values()
    state = io.state()
    assert {o.id: o.value for o in state.outputs} == {"case_light": 1.0, "dimmable_light": 25.0}
    assert [(o.id, o.pwm, o.scale) for o in state.outputs] == [
        ("case_light", False, 1.0), ("dimmable_light", True, 100.0),
    ]
    assert [(i.id, i.value) for i in state.inputs] == [("my_custom_button", True)]


def test_a_fan_is_set_in_percent_and_clamped(service):
    io, fan = service
    io.set_value("fan", 140)
    assert fan.speed.value == 100.0
    io.set_value("fan", -5)
    assert fan.speed.value == 0.0


def test_a_pwm_output_is_clamped_to_its_scale_and_a_switch_is_a_bit(service):
    io, _fan = service
    io.set_value("dimmable_light", 250)
    io.set_value("case_light", 0)
    assert {o.id: o.value for o in io.state().outputs} == {"case_light": 0.0, "dimmable_light": 100.0}


def test_inputs_and_unknown_ids_cannot_be_set(service):
    io, _fan = service
    with pytest.raises(BadRequestError):
        io.set_value("my_custom_button", 1)
    with pytest.raises(NotFoundError):
        io.set_value("nope", 1)


def test_preload_creates_bit_pins_for_switches_and_float_pins_for_pwm(monkeypatch):
    created: list[tuple[str, str, str]] = []

    def fake_pin(kind):
        def make(name, hal_type, description):
            created.append((kind, name, hal_type.name))
            return FakePin()
        return make

    monkeypatch.setattr(io_module, "ReadWriteDynamicHalPin", fake_pin("rw"))
    monkeypatch.setattr(io_module, "ReadOnlyDynamicHalPin", fake_pin("ro"))
    IoService().preload_hal_pins({
        "output_pins": [{"id": "case_light"}, {"id": "dimmable_light", "pwm": True}],
        "input_pins": [{"id": "my_custom_button"}],
    })
    assert created == [
        ("rw", "case_light", "BIT"), ("rw", "dimmable_light", "FLOAT"), ("ro", "my_custom_button", "BIT"),
    ]


def test_the_router_reads_and_sets(service, monkeypatch):
    io, fan = service
    monkeypatch.setattr(io_module, "_service", io)
    from routers import io as io_router

    app = FastAPI()
    register_command_error_handler(app)
    app.include_router(io_router.router)
    client = TestClient(app)

    assert client.put("/api/v1/modules/io/fan", json={"value": 40}).status_code == 200
    body = client.get("/api/v1/modules/io").json()
    assert body["fans"] == [{"id": "fan", "value": 40.0}]
    assert client.put("/api/v1/modules/io/nope", json={"value": 1}).status_code == 404


def test_a_latched_output_is_one_event_and_reads_back_its_state(monkeypatch):
    """An output an input sets (halpin_set) is latched in HAL: the UI writes
    the value, toggles -set, and reads the result from -state."""
    pins: dict[str, FakePin] = {}

    def make(name, hal_type, description):
        pins[name] = FakePin(False if hal_type.name == "BIT" else 0.0)
        return pins[name]

    monkeypatch.setattr(io_module, "ReadWriteDynamicHalPin", make)
    monkeypatch.setattr(io_module, "ReadOnlyDynamicHalPin", make)
    monkeypatch.setattr(io_module, "get_fans_service", lambda: SimpleNamespace(get_halpins=lambda: []))
    io = IoService()
    io.preload_hal_pins({
        "output_pins": [{"id": "case_light", "value": 1}],
        "input_pins": [{"id": "door", "rising_halpin_set": [{"output": "case_light", "value": 1}]}],
    })
    assert set(pins) == {"case_light", "case_light-set", "case_light-state", "door"}

    io.apply_start_values()
    assert (pins["case_light"].value, pins["case_light-set"].value) == (1.0, True)
    io.set_value("case_light", 0)
    assert (pins["case_light"].value, pins["case_light-set"].value) == (0.0, False)  # toggled again

    pins["case_light-state"].value = 1.0  # e.g. the door closed since
    assert io.state().outputs[0].value == 1.0
