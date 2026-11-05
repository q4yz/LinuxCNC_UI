"""The OctoPrint-compatible slicer API (``routers/octoprint.py``): what
OrcaSlicer / PrusaSlicer and Cura's OctoPrint plugin call to send G-code."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_file_services import ProgramFileService
from routers import octoprint
from services import SlicerUploadService as slicer_module
from services.SlicerUploadService import SlicerUploadService


class _FakeMachine(SlicerUploadService):
    def __init__(self, programs, running=False, load_ok=True):
        super().__init__(programs, machine_backend="http://machine.invalid")
        self.running, self.load_ok, self.loaded = running, load_ok, []

    def machine_running(self):
        return self.running

    def load(self, path):
        self.loaded.append(path)
        return self.running and self.load_ok


@pytest.fixture()
def programs(tmp_path):
    return ProgramFileService(root=tmp_path)


@pytest.fixture()
def service(programs, monkeypatch):
    fake = _FakeMachine(programs)
    monkeypatch.setattr(octoprint, "get_slicer_upload_service", lambda: fake)
    return fake


@pytest.fixture()
def client(service):
    app = FastAPI()
    app.include_router(octoprint.router)
    return TestClient(app)


def _upload(client, name="benchy.gcode", **form):
    return client.post(
        "/api/files/local",
        files={"file": (name, b"G28\nG1 X10\n", "application/octet-stream")},
        data=form,
        headers={"X-Api-Key": "anything"},
    )


def test_version_passes_the_slicers_octoprint_check(client):
    body = client.get("/api/version", headers={"X-Api-Key": "anything"}).json()
    assert body["text"].startswith("OctoPrint")  # PrusaSlicer / Orca reject anything else
    assert body["api"] == "0.1"


@pytest.mark.parametrize("path", ["/api/server", "/api/settings", "/api/printerprofiles",
                                  "/api/printer", "/api/job", "/api/connection"])
def test_the_status_routes_answer(client, path):
    assert client.get(path).status_code == 200
    assert client.post("/api/login").json()["active"] is True


def test_upload_stores_the_file_in_nc_files(client, programs, service):
    response = _upload(client)
    assert response.status_code == 201  # OctoPrint's answer, Cura checks it
    local = response.json()["files"]["local"]
    assert local["name"] == "benchy.gcode" and local["origin"] == "local"
    assert (programs.root / "benchy.gcode").read_bytes() == b"G28\nG1 X10\n"
    assert service.loaded == []  # no select / print: nothing loaded


def test_upload_into_a_folder_overwrites(client, programs):
    _upload(client, path="orca/")
    response = _upload(client, path="orca/")
    assert response.status_code == 201
    assert response.json()["files"]["local"]["path"] == "orca/benchy.gcode"
    assert (programs.root / "orca" / "benchy.gcode").is_file()


@pytest.mark.parametrize("flag", ["select", "print"])
def test_select_and_print_only_load_the_file(client, service, flag):
    service.running = True
    body = _upload(client, **{flag: "true"}).json()
    assert service.loaded == ["benchy.gcode"]
    assert body["effectiveSelect"] is True
    assert body["effectivePrint"] is False  # never started from the network


def test_upload_while_linuxcnc_is_off_is_stored_but_not_loaded(client, service, programs):
    body = _upload(client, print="true").json()
    assert body["effectiveSelect"] is False
    assert (programs.root / "benchy.gcode").is_file()


def test_only_gcode_is_accepted(client, programs):
    assert _upload(client, name="model.3mf").status_code == 415
    assert _upload(client, name="../escape.gcode").status_code in (201, 400)
    assert not (programs.root.parent / "escape.gcode").exists()


def test_a_folder_outside_nc_files_is_rejected(client):
    assert _upload(client, path="../outside").status_code == 400


def test_printer_state_follows_linuxcnc(client, service):
    assert client.get("/api/printer").json()["state"]["flags"]["operational"] is False
    service.running = True
    state = client.get("/api/printer").json()["state"]
    assert state["text"] == "Operational" and state["flags"]["ready"] is True


def test_load_is_skipped_while_linuxcnc_is_off(programs, monkeypatch):
    monkeypatch.setattr(slicer_module, "linuxcnc_pids", lambda: [])
    called = []
    monkeypatch.setattr(slicer_module.urllib.request, "urlopen", lambda *a, **k: called.append(a))
    assert SlicerUploadService(programs).load("x.gcode") is False
    assert called == []
