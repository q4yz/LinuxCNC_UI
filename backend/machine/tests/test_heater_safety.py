"""Heaters off when the machine leaves ON (E-stop, power off, a fault) —
and they stay off when it is turned back on (HeaterSafetyService)."""
from __future__ import annotations

import services.temperature.HeaterSafetyService as safety_module
import services.temperature.HeaterService as heater_module
from dtos.tools.ExtruderDto import ExtruderPins
from dtos.tools.HeaterDto import HeaterPins
from hardware import linuxcnc

ON = getattr(linuxcnc, "STATE_ON", 4)
OFF = getattr(linuxcnc, "STATE_OFF", 3)
ESTOP = getattr(linuxcnc, "STATE_ESTOP", 1)


class Pin:
    def __init__(self, value=0.0):
        self.value = value

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value


class Heaters:
    def __init__(self):
        self.calls = 0

    def all_off(self):
        self.calls += 1
        return ["heater_bed"]


class Console:
    def __init__(self):
        self.events = []

    def log_event(self, message, **kwargs):
        self.events.append((message, kwargs))


def _service(monkeypatch):
    heaters, console = Heaters(), Console()
    monkeypatch.setattr(safety_module, "get_console_logger", lambda: console)
    return safety_module.HeaterSafetyService(heaters), heaters, console


def test_leaving_on_turns_the_heaters_off_once(monkeypatch):
    service, heaters, console = _service(monkeypatch)
    assert service.observe(ON) == []
    assert service.observe(ON) == []
    assert service.observe(OFF) == ["heater_bed"]       # the following error / power off
    assert heaters.calls == 1
    assert "heaters turned off (heater_bed)" in console.events[0][0]
    assert console.events[0][1]["level"].value == "WARNING"
    # off stays off; turning back on does not restore anything
    assert service.observe(OFF) == []
    assert service.observe(ON) == []
    assert heaters.calls == 1


def test_estop_counts_too(monkeypatch):
    service, heaters, _ = _service(monkeypatch)
    service.observe(ON)
    assert service.observe(ESTOP) == ["heater_bed"]


def test_nothing_before_the_machine_was_on(monkeypatch):
    service, heaters, _ = _service(monkeypatch)
    assert service.observe(ESTOP) == []
    assert service.observe(OFF) == []
    assert heaters.calls == 0


def test_all_off_zeroes_every_heater_and_extruder(monkeypatch):
    bed = HeaterPins(id="heater_bed", target_temperature=Pin(60.0))
    hotend = HeaterPins(id="heater_extruder", target_temperature=Pin(210.0))
    cold = HeaterPins(id="heater_chamber", target_temperature=Pin(0.0))

    class Tools:
        def get_halpins(self):
            return [bed, ExtruderPins(id="extruder", heater=hotend), cold, object()]

    monkeypatch.setattr(heater_module, "tool_service", Tools())
    assert heater_module.HeaterService().all_off() == ["heater_bed", "heater_extruder"]
    assert (bed.target_temperature.value, hotend.target_temperature.value, cold.target_temperature.value) == (0.0, 0.0, 0.0)


def test_the_telemetry_loop_feeds_it():
    import inspect

    from services.machine.ServoThreadService import ServoThreadService

    source = inspect.getsource(ServoThreadService.telemetry_loop)
    assert 'self.heater_safety.observe(int(getattr(stat, "task_state", 0) or 0))' in source
