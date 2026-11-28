"""LinuxCNC starts with the system service (`MachineAutostart`)."""
from __future__ import annotations

import services.MachineAutostart as autostart
import services.MachineLifecycleService as lifecycle_mod


class Lifecycle:
    def __init__(self, machine="m8p", running=False, fail=None):
        self.machine, self.running, self.fail, self.starts = machine, running, fail, 0

    def default_machine(self):
        return self.machine

    def is_running(self):
        return self.running

    def start(self):
        self.starts += 1
        if self.fail:
            raise self.fail


def _rig(monkeypatch, enabled=True, **kw):
    fake = Lifecycle(**kw)
    monkeypatch.setattr(lifecycle_mod, "get_machine_lifecycle_service", lambda: fake)
    monkeypatch.setattr(autostart, "autostart_enabled", lambda: enabled)
    return fake


def test_starts_the_default_machine(monkeypatch):
    fake = _rig(monkeypatch)
    assert autostart.autostart_once() == "started"
    assert fake.starts == 1


def test_switched_off(monkeypatch):
    fake = _rig(monkeypatch, enabled=False)
    assert autostart.autostart_once() == "off"
    assert fake.starts == 0


def test_no_default_machine_or_already_running(monkeypatch):
    assert autostart.autostart_once.__name__  # import ok
    fake = _rig(monkeypatch, machine=None)
    assert autostart.autostart_once() == "no default machine"
    fake = _rig(monkeypatch, running=True)
    assert autostart.autostart_once() == "already running"
    assert fake.starts == 0


def test_a_failed_start_does_not_raise(monkeypatch):
    _rig(monkeypatch, fail=RuntimeError("boom"))
    assert autostart.autostart_once().startswith("failed")


def test_on_unless_switched_off(monkeypatch):
    import services.UiSettingsService as settings_mod

    class Store:
        def __init__(self, value): self.value = value
        def read(self, key):
            if self.value is None:
                raise KeyError(key)
            return self.value

    for value, expected in ((None, True), (True, True), (False, False)):
        monkeypatch.setattr(settings_mod, "get_ui_settings_service", lambda v=value: Store(v))
        assert autostart.autostart_enabled() is expected
