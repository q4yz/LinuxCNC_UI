"""PID_CALIBRATE: the relay test against a simulated first-order heater
with dead time, the gains, the limits, the heater handed back."""
from __future__ import annotations

import math

import pytest

import services.calibration.PidCalibrateService as module
from dtos.calibration.CalibrationPinsDto import PidCalibratePins, PidTunePins
from exceptions import BadRequestError

HEATER = {"id": "heater_extruder", "type": "extruder", "control": "pid", "max_temp": 280, "max_power": 1.0}


class Plant:
    """dT/dt = (gain * duty% - (T - ambient)) / tau, with dead time."""

    def __init__(self, gain=3.0, tau=60.0, dead=4.0, dt=0.1):
        self.t, self.temp, self.dt, self.gain, self.tau = 0.0, 25.0, dt, gain, tau
        self.queue = [0.0] * int(dead / dt)
        self.duty = 0.0

    def step(self):
        self.queue.append(self.duty)
        applied = self.queue.pop(0)
        self.temp += (self.gain * applied - (self.temp - 25.0)) / self.tau * self.dt
        self.t += self.dt


class RecPin:
    """Records every write as (``<heater>-<enable|duty>``, value)."""

    def __init__(self, svc, key):
        self.svc, self.key = svc, key

    def set_value(self, value):
        self.svc.writes.append((self.key, value))
        if self.key.endswith("-duty"):
            self.svc.plant.duty = value


class Svc(module.PidCalibrateService):
    def __init__(self, plant):
        super().__init__()
        self.plant, self.writes = plant, []
        self._pins = PidCalibratePins(heaters=tuple(
            PidTunePins(heater_id=h["id"], enable=RecPin(self, f"{h['id']}-enable"), duty=RecPin(self, f"{h['id']}-duty"))
            for h in self._heaters()))

    @staticmethod
    def _heaters():
        return [HEATER, {"id": "heater_bed", "type": "heated_bed", "control": "pid"}]


def run(plant, svc, target=200.0):
    events = []
    return svc.calibrate(HEATER, target, lambda: plant.temp, lambda: plant.t, lambda s: plant.step(),
                         lambda m, **k: events.append(m)), events


def test_relay_autotune_gives_ziegler_nichols_gains():
    plant = Plant()
    svc = Svc(plant)
    (kp, ki, kd), events = run(plant, svc)
    # The relay oscillation of this plant: Ku = 4*100/(pi*a); gains must be positive and sane.
    assert 1.0 < kp < 50.0 and 0.01 < ki < kp and kd > kp
    tu = 2 * kp / ki  # Ti = 0.5 Tu
    assert 10.0 < tu < 120.0
    assert "pid_Kp=" in events[-1]
    # handed back to the PID loop at the end
    assert svc.writes[-2:] == [("heater_extruder-duty", 0.0), ("heater_extruder-enable", False)]


def test_overshoot_aborts_and_releases():
    plant = Plant(gain=10.0, tau=5.0, dead=20.0)
    svc = Svc(plant)
    with pytest.raises(module.PidCalibrateError, match="over the target"):
        run(plant, svc, target=100.0)
    assert svc.writes[-1] == ("heater_extruder-enable", False)


def test_heater_that_never_gets_there_times_out(monkeypatch):
    monkeypatch.setattr(module, "PEAK_TIMEOUT_S", 30.0)
    plant = Plant(gain=0.5)  # 75 °C at most
    with pytest.raises(module.PidCalibrateError, match="did not reach"):
        run(plant, Svc(plant))


def test_tuner_math():
    tuner = module.RelayTuner(200.0, 100.0)
    tuner.peaks = [(205.0, 10.0), (195.0, 20.0), (205.0, 30.0), (195.0, 40.0)]
    kp, ki, kd = tuner.result()
    ku = 400.0 / (math.pi * 5.0)
    assert kp == pytest.approx(0.6 * ku) and ki == pytest.approx(kp / 10.0) and kd == pytest.approx(kp * 2.5)


def test_parsing_and_resolving():
    assert module.parse_command("PID_CALIBRATE HEATER=extruder TARGET=210 ; x") == {"HEATER": "extruder",
                                                                                   "TARGET": "210"}
    assert module.parse_command("PID_CALIBRATEX") is None
    svc = Svc(Plant())
    assert svc.resolve("extruder")["id"] == "heater_extruder"
    assert svc.resolve("HEATER_BED")["id"] == "heater_bed"
    with pytest.raises(BadRequestError, match="no PID heater"):
        svc.resolve("chamber")
    with pytest.raises(BadRequestError, match="TARGET"):
        svc.run_command("PID_CALIBRATE HEATER=extruder")
    with pytest.raises(BadRequestError, match="outside"):
        svc.run_command("PID_CALIBRATE HEATER=extruder TARGET=279")


def test_estop_aborts_and_releases():
    plant = Plant()
    svc = Svc(plant)
    with pytest.raises(module.PidCalibrateError, match="E-stop"):
        svc.calibrate(HEATER, 200.0, lambda: plant.temp, lambda: plant.t, lambda s: plant.step(),
                      lambda m, **k: None, estop=lambda: plant.t > 30)
    assert svc.writes[-1] == ("heater_extruder-enable", False)
