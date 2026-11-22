"""Input shaper / skew at runtime and the resonance test signal (ShaperService)."""
from __future__ import annotations

import pytest

import services.calibration.ShaperService as module
from exceptions import BadRequestError


class Pin:
    def __init__(self):
        self.value = None

    def set_value(self, value):
        self.value = value


@pytest.fixture
def service(monkeypatch):
    s = module.ShaperService()
    s._pins = {name: Pin() for name in module._PINS}
    payload = {"input_shaper": {"freq_x": 50.0, "freq_y": 40.0}, "skew_correction": {"xy_factor": 0.001}}
    monkeypatch.setattr(module.ShaperService, "_payload", staticmethod(lambda: payload))

    class Console:
        def log_event(self, *a, **k):
            pass

    import services.machine.ConsoleLogger as console_module
    monkeypatch.setattr(console_module, "get_console_logger", lambda: Console())
    return s


def test_starts_at_the_profile(service, monkeypatch):
    monkeypatch.setattr(module, "ReadWriteDynamicHalPin", lambda name, *a: service._pins[name])
    service.preload_hal_pins()
    service.apply_initial()
    assert service._pins["shaper-freq-x"].value == 50.0 and service._pins["shaper-freq-y"].value == 40.0
    assert service._pins["skew-xy"].value == 0.001 and service._pins["resonance-amp-x"].value == 0.0


def test_set_input_shaper(service):
    assert service.run_command("SET_INPUT_SHAPER SHAPER_FREQ_X=61.2")
    assert service._pins["shaper-freq-x"].value == 61.2 and service.freq["y"] == 0.0
    with pytest.raises(BadRequestError):
        service.run_command("SET_INPUT_SHAPER SHAPER_FREQ_Y=900")


def test_set_skew(service):
    assert service.run_command("SET_SKEW XY=142.0,140.8,100")
    assert service._pins["skew-xy"].value == pytest.approx(0.0084867, rel=1e-3)
    assert service.run_command("SET_SKEW CLEAR=1") and service._pins["skew-xy"].value == 0.0
    for bad in ("SET_SKEW XY=1,2", "SET_SKEW XY=100,100,200", "SET_SKEW"):
        with pytest.raises(BadRequestError):
            service.run_command(bad)
    assert service.run_command("G0 X1") is False


def test_needs_the_sections(service, monkeypatch):
    monkeypatch.setattr(module.ShaperService, "_payload", staticmethod(lambda: {}))
    with pytest.raises(BadRequestError):
        service.run_command("SET_INPUT_SHAPER SHAPER_FREQ_X=50")


def test_test_signal(service):
    service.test_signal("y", 0.05, 40.0)
    assert service._pins["resonance-amp-y"].value == 0.05 and service._pins["resonance-amp-x"].value == 0.0
    assert service._pins["resonance-freq"].value == 40.0
    service.stop_test()
    assert service._pins["resonance-amp-y"].value == 0.0


def test_available_on_corexy_too(monkeypatch):
    """CoreXY shapes X / Y before the belt mixing (CoreXyHalMapper)."""
    from services.calibration.ShaperService import ShaperService

    svc = ShaperService()
    monkeypatch.setattr(ShaperService, "_payload", staticmethod(lambda: {"kinematics": "corexy", "skew_correction": {}}))
    assert svc.available()
    monkeypatch.setattr(ShaperService, "_payload", staticmethod(lambda: {"kinematics": "corexy"}))
    assert not svc.available()
