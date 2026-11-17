"""The Calibration tab's service: the catalog from the machine, results and
reminders in calibration.ini, start, clear; the REST routes."""
from __future__ import annotations

import datetime as dt

import pytest

import services.CalibrationService as module
from exceptions import BadRequestError, NotFoundError

PAYLOAD = {
    "probe": {"pin": "PB7", "z_offset": 1.0},
    "bed_mesh": {"probe_count": [3, 3]},
    "tools": [{"id": "heater_extruder", "type": "extruder", "control": "pid", "max_temp": 280, "pid_kp": 10.0,
               "pid_ki": 1.0, "pid_kd": 50.0},
              {"id": "heater_bed", "type": "heated_bed", "control": "pid", "max_temp": 110}],
}


@pytest.fixture
def svc(monkeypatch):
    import services.HardwareConfigService as hw
    import services.ShaperService as shaper

    monkeypatch.setattr(hw.HardwareConfigService, "load_payload", lambda self: PAYLOAD)
    monkeypatch.setattr(shaper.ShaperService, "available", lambda self: False)
    sent = []

    class State:
        def run_mdi(self, command):
            sent.append(command)

    import services.StateService as state

    monkeypatch.setattr(state, "get_state_service", lambda: State())
    service = module.CalibrationService()
    service.sent = sent
    return service


def _item(listing, cid):
    return next(i for i in listing["items"] if i["id"] == cid)


def test_catalog_follows_the_machine(svc):
    listing = svc.listing()
    ids = [i["id"] for i in listing["items"]]
    assert ids == ["bed_mesh", "z_tilt", "probe_accuracy", "probe_z_offset", "pid_heater_extruder", "pid_heater_bed",
                   "input_shaper"]
    assert _item(listing, "bed_mesh")["available"] and not _item(listing, "z_tilt")["available"]
    assert "z_tilt" in _item(listing, "z_tilt")["reason"]
    pid = _item(listing, "pid_heater_extruder")
    assert pid["params"][0]["default"] == 210 and pid["params"][0]["maximum"] == 275
    assert pid["values"] == {"kp": 10.0, "ki": 1.0, "kd": 50.0, "calibrated": False}
    assert _item(listing, "pid_heater_bed")["params"][0]["default"] == 60


def test_start_sends_the_command(svc):
    assert svc.start("pid_heater_extruder", {"target": 215}) == "PID_CALIBRATE HEATER=heater_extruder TARGET=215"
    assert svc.start("probe_accuracy", {}) == "PROBE_ACCURACY SAMPLES=10"
    assert svc.sent == ["PID_CALIBRATE HEATER=heater_extruder TARGET=215", "PROBE_ACCURACY SAMPLES=10"]
    with pytest.raises(BadRequestError, match="outside"):
        svc.start("pid_heater_extruder", {"target": 300})
    with pytest.raises(BadRequestError, match="z_tilt"):
        svc.start("z_tilt", {})
    with pytest.raises(NotFoundError):
        svc.start("nope", {})


def test_results_and_reminders(svc, monkeypatch):
    svc.set_reminder("bed_mesh", "2026-01-10")
    monkeypatch.setattr(module, "_today", lambda: dt.date(2026, 1, 9))
    assert not _item(svc.listing(), "bed_mesh")["due"] and svc.listing()["due"] == 0
    monkeypatch.setattr(module, "_today", lambda: dt.date(2026, 1, 10))
    assert _item(svc.listing(), "bed_mesh")["due"] and svc.listing()["due"] == 1
    module.record("bed_mesh", "3 × 3, range 0.120 mm")
    item = _item(svc.listing(), "bed_mesh")
    assert item["result"] == "3 × 3, range 0.120 mm" and item["last_tested"] and item["remind_at"] is None
    # a reminder not yet due stays after a run
    svc.set_reminder("bed_mesh", "2026-02-01")
    module.record("bed_mesh", "again")
    assert _item(svc.listing(), "bed_mesh")["remind_at"] == "2026-02-01"
    with pytest.raises(BadRequestError):
        svc.set_reminder("bed_mesh", "soon")


def test_pid_result_saved_applied_and_cleared(svc, monkeypatch):
    calls = []
    monkeypatch.setattr(module, "halcmd_setp", lambda name, value: calls.append((name, value)) or True)
    module.record_pid("heater_extruder", 12.3456, 0.5, 80.0)
    store = module.calibration_file()
    assert store.load()["HEATER_EXTRUDER"] == {"PID_KP": "12.3456", "PID_KI": "0.5", "PID_KD": "80"}
    assert ("PID-heater_extruder.KP", "12.3456") in calls
    pid = _item(svc.listing(), "pid_heater_extruder")
    assert pid["values"]["kp"] == 12.3456 and pid["values"]["calibrated"] is True
    assert pid["result"].startswith("Kp 12.346")
    svc.clear("pid_heater_extruder")
    assert "HEATER_EXTRUDER" not in store.load()
    assert _item(svc.listing(), "pid_heater_extruder")["values"]["kp"] == 10.0
    with pytest.raises(BadRequestError):
        svc.clear("bed_mesh")


def test_input_shaper_result(monkeypatch):
    calls, shaped = [], []
    monkeypatch.setattr(module, "halcmd_setp", lambda name, value: calls.append((name, value)) or True)
    monkeypatch.setattr(module, "_axis_joints", lambda axis: [0] if axis == "x" else [1])
    import services.ShaperService as shaper

    monkeypatch.setattr(shaper.ShaperService, "set_shaper", lambda self, axis, freq: shaped.append((axis, freq)))
    module.record_input_shaper("x", "ei", 52.44, 0.04)
    module.record_input_shaper("y", "mzv", 41.0, 0.06)
    data = module.calibration_file().load()
    assert data["CALIBRATION"]["SHAPER_FREQ_X"] == "52.4" and data["CALIBRATION"]["SHAPER_TYPE_Y"] == "mzv"
    assert data["INPUT_SHAPER"] == {"TYPE_X": "4", "TYPE_Y": "2"}
    assert ("shape-j0.shaper-type", 4) in calls and shaped == [("x", 52.44), ("y", 41.0)]
    assert module.calibration_file().state("input_shaper")["result"].startswith("X ei 52.4 Hz, Y mzv 41.0 Hz")


def test_router(svc):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import calibration

    app = FastAPI()
    app.include_router(calibration.router)
    client = TestClient(app)
    assert client.get("/api/v1/calibration").json()["items"][0]["id"] == "bed_mesh"
    assert client.post("/api/v1/calibration/bed_mesh/start", json={}).json() == {"command": "BED_MESH_CALIBRATE"}
    body = client.put("/api/v1/calibration/bed_mesh/reminder", json={"remind_at": "2030-01-01"}).json()
    assert _item(body, "bed_mesh")["remind_at"] == "2030-01-01"
