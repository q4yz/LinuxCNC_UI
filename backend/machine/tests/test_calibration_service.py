"""The Calibration tab's service: the catalog from the machine, results and
reminders in calibration.ini, start, clear; the REST routes."""
from __future__ import annotations

import datetime as dt

import pytest

import services.CalibrationService as module
from exceptions import BadRequestError, NotFoundError

PAYLOAD = {
    "axes": [{"id": "x", "position_min": 0, "position_max": 235}, {"id": "y", "position_min": 0, "position_max": 235},
             {"id": "z", "position_max": 250, "joint_numbers": [2]}],
    "joints": [{"id": "heater_extruder", "joint_number": 3}],
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
                   "input_shaper", "skew", "pressure_advance", "extruder_steps", "flow", "first_layer"]
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


@pytest.fixture
def guided(svc, monkeypatch):
    """Skew available (jointshape), test prints captured instead of run."""
    import services.ShaperService as shaper

    monkeypatch.setattr(shaper.ShaperService, "available", lambda self: True)
    shaper_service = shaper.ShaperService()
    shaper_service.skew = 0.001
    applied = {}
    monkeypatch.setattr(shaper_service, "set_skew", lambda f: applied.__setitem__("skew", f))
    monkeypatch.setattr(shaper, "get_shaper_service", lambda: shaper_service)
    import services.PrintTuningService as tuning

    class Tuning:
        flow = 100.0
        z_offset = 0.0

        def state(self, path, line):
            return {"pressure_advance": 0.03}

        def set_pressure_advance(self, k):
            applied["pa"] = k

        def set_flow(self, f):
            applied["flow"] = f

    tuning_service = Tuning()
    monkeypatch.setattr(tuning, "get_print_tuning_service", lambda: tuning_service)
    prints = {}
    monkeypatch.setattr(module, "start_test_print", lambda name, text: prints.__setitem__(name, text) or f"test print {name}")
    ini = {}
    monkeypatch.setattr(module, "ini_value", lambda section, key: ini.get((section, key)))
    return type("G", (), {"svc": svc, "prints": prints, "applied": applied, "tuning": tuning_service, "ini": ini})


def test_skew_prints_then_takes_the_measurements(guided):
    card = _item(guided.svc.listing(), "skew")
    assert card["guided"] and card["figure"] == "skew" and [i["name"] for i in card["inputs"]] == ["ac", "bd", "ad"]
    assert guided.svc.start("skew", {"hotend": 215, "bed": 65, "size": 80}) == "test print skew_square"
    text = guided.prints["skew_square"]
    assert "M104 S215" in text and "M140 S65" in text and "skew square 80 mm" in text
    # printed with 0.001 already; the measured parallelogram shows a residual 0.002
    import math
    L, r = 80.0, 0.002
    A, B, C, D = (0, 0), (L, 0), (L + r * L, L), (r * L, L)
    d = lambda p, q: math.hypot(p[0] - q[0], p[1] - q[1])
    result = guided.svc.submit("skew", {"ac": d(A, C), "bd": d(B, D), "ad": d(A, D)})
    assert result.startswith("factor 0.003000")
    assert guided.applied["skew"] == pytest.approx(0.003)
    assert module.calibration_file().number("SKEW_XY") == pytest.approx(0.003)
    with pytest.raises(BadRequestError, match="enter a number"):
        guided.svc.submit("skew", {"ac": 141})


def test_pressure_advance_tower_then_the_height(guided):
    with pytest.raises(BadRequestError, match="Print the tower first"):
        guided.svc.submit("pressure_advance", {"height": 12})
    guided.svc.start("pressure_advance", {"hotend": 210, "bed": 60, "start": 0, "factor": 0.005, "height": 30,
                                          "speed": 100})
    text = guided.prints["pressure_advance_tower"]
    assert text.rstrip().splitlines()[-1] == "M2" and "SET_PRESSURE_ADVANCE ADVANCE=0.0300" in text  # restored
    assert guided.svc.submit("pressure_advance", {"height": 12}).startswith("K 0.0600")
    assert guided.applied["pa"] == 0.06 and module.calibration_file().number("PRESSURE_ADVANCE") == 0.06
    with pytest.raises(BadRequestError, match="only 30 mm"):
        guided.svc.submit("pressure_advance", {"height": 45})
    guided.svc.clear("pressure_advance")
    assert module.calibration_file().number("PRESSURE_ADVANCE") is None


def test_automatic_calibrations_take_no_measurements(svc):
    with pytest.raises(BadRequestError, match="measures by itself"):
        svc.submit("bed_mesh", {})


def test_start_test_print_converts_loads_and_starts(monkeypatch, tmp_path):
    import hardware
    import services.ProgramService as program
    from domain_file_services import paths
    from hardware.Connection import MachineState

    class Stat:
        estop, task_state, interp_state, file = False, MachineState.ON.value, 1, ""

        def poll(self):
            pass

    stat = Stat()
    monkeypatch.setattr(hardware, "get_stat_channel", lambda: stat)
    monkeypatch.setattr(paths, "NC_FILES_DIR", tmp_path)
    calls = []

    class Program:
        def load_program(self, path):
            calls.append(("load", path))

        def start_program(self):
            calls.append(("start",))

    monkeypatch.setattr(program, "get_program_lifecycle_service", lambda: Program())
    assert module.start_test_print("skew_square", "G28\nG1 X10 Y10 E1 F600\n") == "test print calibration/skew_square.ngc"
    ngc = tmp_path / "calibration" / "skew_square.ngc"
    assert "LINUXCNC_UI_PRESTART" in ngc.read_text() and " A1" in ngc.read_text()
    assert calls == [("load", str(ngc)), ("start",)]
    stat.estop = True
    with pytest.raises(BadRequestError, match="E-stop"):
        module.start_test_print("skew_square", "G1 X1\n")


def test_extruder_steps(guided):
    guided.ini[("JOINT_3", "SCALE")] = 93.0
    card = _item(guided.svc.listing(), "extruder_steps")
    assert card["available"] and card["values"] == {"scale": 93.0, "joint": 3}
    guided.svc.start("extruder_steps", {"hotend": 200, "length": 100, "speed": 1})
    assert "G1 E100 F60" in guided.prints["extrude_100"]
    result = guided.svc.submit("extruder_steps", {"mark": 120, "remaining": 23})  # 97 of 100 mm
    assert result.startswith("SCALE 93.000 → 95.876")
    assert module.calibration_file().load()["JOINT_3"] == {"SCALE": "95.8763"}
    with pytest.raises(BadRequestError, match="20 %"):
        guided.svc.submit("extruder_steps", {"mark": 120, "remaining": 60})
    guided.svc.clear("extruder_steps")
    assert "JOINT_3" not in module.calibration_file().load()


def test_flow(guided):
    guided.tuning.flow = 98.0
    guided.svc.start("flow", {"hotend": 210, "bed": 60, "size": 30})
    assert "flow cube 30 mm" in guided.prints["flow_cube"]
    assert guided.svc.submit("flow", {"wall": 0.49}).startswith("flow 90 %")
    assert guided.applied["flow"] == 90.0 and module.calibration_file().number("FLOW") == 90.0
    with pytest.raises(BadRequestError, match="implausible"):
        guided.svc.submit("flow", {"wall": 0.9})


def test_first_layer_into_the_probe_z_offset(guided):
    assert module.first_layer_target(PAYLOAD) == "probe"  # a mesh with absolute heights
    guided.svc.start("first_layer", {"hotend": 210, "bed": 60})
    assert guided.prints["first_layer"].count("; patch ") == 5
    with pytest.raises(BadRequestError, match="is 0"):
        guided.svc.submit("first_layer", {})
    guided.tuning.z_offset = 0.05  # the nozzle had to go up
    assert "z_offset 0.950 mm saved" in guided.svc.submit("first_layer", {})
    assert module.calibration_file().number("PROBE_Z_OFFSET") == 0.95


def test_first_layer_into_z_home_offset(guided, monkeypatch):
    import services.HardwareConfigService as hw

    no_probe = {k: v for k, v in PAYLOAD.items() if k != "probe"}
    monkeypatch.setattr(hw.HardwareConfigService, "load_payload", lambda self: no_probe)
    assert module.first_layer_target(no_probe) == "endstop"
    guided.ini[("JOINT_2", "HOME_OFFSET")] = 0.0
    guided.tuning.z_offset = -0.08  # the nozzle had to go down
    assert "Z's home position saved" in guided.svc.submit("first_layer", {})
    assert module.calibration_file().load()["JOINT_2"] == {"HOME_OFFSET": "0.08"}
