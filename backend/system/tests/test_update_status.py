"""System update progress: scripts/update_status.py writes it, UpdateService
reports it, ``/api/v1/system/update[/status]`` serves it."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_file_services.paths import PROJECT_ROOT
from routers import SystemRouter
from services.UpdateService import UpdateService, set_update_service

STATUS_SCRIPT = PROJECT_ROOT / "scripts" / "update_status.py"


def _write(status_file, run_id, *args):
    env = {**os.environ, "UPDATE_STATUS_FILE": str(status_file), "UPDATE_RUN_ID": run_id}
    subprocess.run([sys.executable, str(STATUS_SCRIPT), *args], env=env, check=True, timeout=30)
    return json.loads(status_file.read_text(encoding="utf-8"))


@pytest.fixture()
def service(tmp_path, monkeypatch):
    script = tmp_path / "update.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    svc = UpdateService(status_file=tmp_path / "update_status.json", script=script, log_file=tmp_path / "update.log")
    launched: list[dict[str, str]] = []
    monkeypatch.setattr(svc, "_launch", lambda env: launched.append(env))
    svc.launched = launched
    return svc


# -- the status writer (scripts/update_status.py) ------------------------- #


def test_writer_keeps_the_run_start_across_phases(tmp_path):
    status_file = tmp_path / "s.json"
    first = _write(status_file, "run1", "running", "pull")
    later = _write(status_file, "run1", "running", "dependencies")
    done = _write(status_file, "run1", "done", "finished", "Update complete")

    assert later["started_at"] == first["started_at"]
    assert done["state"] == "done" and done["phase"] == "finished"
    assert done["finished_at"] is not None
    assert done["commit_before"] == first["commit_before"]
    assert first["finished_at"] is None


def test_writer_starts_fresh_for_a_new_run(tmp_path):
    status_file = tmp_path / "s.json"
    _write(status_file, "run1", "done", "finished")
    nxt = _write(status_file, "run2", "running", "starting")
    assert nxt["run_id"] == "run2"
    assert nxt["state"] == "running"
    assert nxt["finished_at"] is None


def test_writer_rejects_unknown_states(tmp_path):
    env = {**os.environ, "UPDATE_STATUS_FILE": str(tmp_path / "s.json")}
    result = subprocess.run([sys.executable, str(STATUS_SCRIPT), "bogus", "x"], env=env, capture_output=True)
    assert result.returncode == 2
    assert not (tmp_path / "s.json").exists()


# -- UpdateService -------------------------------------------------------- #


def test_idle_when_no_update_ever_ran(service):
    assert service.status().state == "idle"


def test_start_records_the_run_before_launching(service):
    run_id = service.start()
    status = service.status()
    assert status.run_id == run_id
    assert (status.state, status.phase) == ("running", "starting")
    [env] = service.launched
    assert env["UPDATE_RUN_ID"] == run_id
    assert env["UPDATE_STATUS_FILE"] == str(service._status_file)


def test_second_start_while_running_is_a_conflict(service):
    service.start()
    with pytest.raises(Exception) as exc_info:
        service.start()
    assert getattr(exc_info.value, "status_code", None) == 409


def test_a_finished_run_allows_a_new_one(service):
    first = service.start()
    _write(service._status_file, first, "done", "finished")
    assert service.start() != first


def test_stale_running_status_reports_failed(service):
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    service._status_file.write_text(json.dumps({
        "run_id": "dead", "state": "running", "phase": "rebuilding UI", "updated_at": old,
    }), encoding="utf-8")
    status = service.status()
    assert status.state == "failed"
    assert "died" in status.message


def test_malformed_status_file_is_idle(service):
    service._status_file.write_text("{not json", encoding="utf-8")
    assert service.status().state == "idle"


# -- HTTP ----------------------------------------------------------------- #


@pytest.fixture()
def client(service):
    set_update_service(service)
    app = FastAPI()
    app.include_router(SystemRouter.router)
    yield TestClient(app)
    set_update_service(None)


def test_endpoints_start_and_report(client):
    assert client.get("/api/v1/system/update/status").json()["state"] == "idle"

    resp = client.post("/api/v1/system/update")
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    status = client.get("/api/v1/system/update/status").json()
    assert status["run_id"] == run_id
    assert status["state"] == "running"

    assert client.post("/api/v1/system/update").status_code == 409
