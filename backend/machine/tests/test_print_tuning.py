"""Print tuning: the live Z offset, flow, excluded objects, slicer progress."""
from __future__ import annotations

import pytest

import services.PrintTuningService as module
from exceptions import BadRequestError


class Pin:
    def __init__(self):
        self.value = None

    def set_value(self, value):
        self.value = value


@pytest.fixture
def service():
    s = module.PrintTuningService()
    s._pins = {name: Pin() for name in ["z-offset", "flow", *[f"exclude-object-{k}" for k in range(32)]]}
    return s


PRINT = """; LINUXCNC_UI_PRESTART: home
G92.1
; LINUXCNC_UI_OBJECTS: ["box", "cyl"]
G1 X1 A1
; M73 P0 R10  ; [not a LinuxCNC M-code]
G1 X2 A2
; M73 P50 R5  ; [not a LinuxCNC M-code]
G1 X3 A3
; M73 L3  ; [not a LinuxCNC M-code]
M2
"""


def test_z_offset_set_adjust_and_limit(service):
    assert service.set_z_offset(0.1) == 0.1 and service._pins["z-offset"].value == 0.1
    assert service.adjust_z_offset(-0.05) == pytest.approx(0.05)
    with pytest.raises(BadRequestError):
        service.set_z_offset(3)


def test_flow_limits(service):
    assert service.set_flow(95) == 95 and service._pins["flow"].value == 95
    for bad in (5, 600):
        with pytest.raises(BadRequestError):
            service.set_flow(bad)


def test_set_gcode_offset_console_command(service, monkeypatch):
    class Console:
        def log_event(self, *a, **k):
            pass

    import services.ConsoleLogger as console_module
    monkeypatch.setattr(console_module, "get_console_logger", lambda: Console())
    assert service.run_command("SET_GCODE_OFFSET Z=0.2") and service.z_offset == 0.2
    assert service.run_command("set_gcode_offset Z_ADJUST=-0.05 MOVE=1") and service.z_offset == pytest.approx(0.15)
    assert service.run_command("G0 X1") is False
    with pytest.raises(BadRequestError):
        service.run_command("SET_GCODE_OFFSET X=1")


def test_objects_and_progress_of_the_loaded_file(service, tmp_path):
    path = tmp_path / "print.ngc"
    path.write_text(PRINT)
    state = service.state(str(path), 1)
    assert [o["name"] for o in state["objects"]] == ["box", "cyl"]
    assert state["progress"] is None  # before the first M73
    assert service.state(str(path), 6)["progress"] == {"percent": 0.0, "remaining_min": 10.0}
    assert service.state(str(path), 9)["progress"] == {"percent": 50.0, "remaining_min": 5.0}
    service.set_excluded(1, True, str(path))
    assert service._pins["exclude-object-1"].value is True
    assert service.state(str(path), 9)["objects"][1]["excluded"] is True
    with pytest.raises(BadRequestError):
        service.set_excluded(5, True, str(path))
    service.reset_objects()
    assert service._pins["exclude-object-1"].value is False
    assert not any(o["excluded"] for o in service.state(str(path), 9)["objects"])


def test_a_different_file_resets_the_exclusions(service, tmp_path):
    first, second = tmp_path / "a.ngc", tmp_path / "b.ngc"
    first.write_text(PRINT)
    second.write_text(PRINT)
    service.set_excluded(0, True, str(first))
    assert service.state(str(second), 1)["objects"][0]["excluded"] is False


def test_m73_index_and_progress_at():
    index = module.m73_index(["M73 P10 R40", "G1 X1", "; M73 P20  ; [x]", "; M73 R30"])
    assert index == [(1, 10.0, 40.0), (3, 20.0, None), (4, None, 30.0)]
    assert module.progress_at(index, 4) == module.Progress(20.0, 30.0)


def test_router(monkeypatch, service, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routers.print_tuning as router_module

    path = tmp_path / "print.ngc"
    path.write_text(PRINT)
    monkeypatch.setattr(router_module, "get_print_tuning_service", lambda: service)
    monkeypatch.setattr(router_module, "_loaded", lambda: (str(path), 9))
    app = FastAPI()
    app.include_router(router_module.router)
    client = TestClient(app)
    body = client.put("/api/v1/print-tuning", json={"z_adjust": 0.05, "flow": 97}).json()
    assert body["z_offset"] == 0.05 and body["flow"] == 97 and body["progress"]["percent"] == 50.0
    body = client.put("/api/v1/print-tuning/objects/0", json={"excluded": True}).json()
    assert body["objects"][0] == {"index": 0, "name": "box", "excluded": True}
    assert client.put("/api/v1/print-tuning", json={"flow": 1}).status_code == 400
