"""G-code programs in project folders: list, upload into a folder,
read/write/delete subpaths, create / move / copy / recursive delete."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import FilesRouter as files_router_module
from services import ProgramFileService

BASE = "/api/v1/programs"


@pytest.fixture()
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path]:
    nc_files = tmp_path / "nc_files"
    (nc_files / "project" / "v2").mkdir(parents=True)
    (nc_files / "top.ngc").write_text("G0 X0\n", encoding="utf-8")
    (nc_files / "project" / "a.ngc").write_text("G0 X1\n", encoding="utf-8")
    (nc_files / "project" / "v2" / "b.ngc").write_text("G0 X2\n", encoding="utf-8")
    (nc_files / "EmptyProgram.ngc").write_text("%\n", encoding="utf-8")
    monkeypatch.setattr(files_router_module, "get_program_service", lambda: ProgramFileService(root=nc_files))
    app = FastAPI()
    app.include_router(files_router_module.router)
    return TestClient(app), nc_files


def test_list_returns_folders_and_nested_files_without_the_empty_program(api):
    client, _ = api
    entries = {e["path"]: e for e in client.get(BASE).json()}
    assert entries["project"]["kind"] == "folder"
    assert entries["project/v2/b.ngc"]["parent"] == "project/v2"
    assert entries["top.ngc"]["parent"] is None
    assert "EmptyProgram.ngc" not in entries


def test_read_write_and_thumbnail_work_on_subpaths(api):
    client, nc_files = api
    # Both a literal and an encoded slash reach the file.
    assert client.get(f"{BASE}/content/project/v2/b.ngc").json() == "G0 X2\n"
    assert client.get(f"{BASE}/content/{quote('project/v2/b.ngc', safe='')}").json() == "G0 X2\n"

    assert client.put(f"{BASE}/content/project/a.ngc", json={"content": "G0 X9\n"}).status_code == 200
    assert (nc_files / "project" / "a.ngc").read_text(encoding="utf-8") == "G0 X9\n"
    assert client.get(f"{BASE}/thumbnail/project/a.ngc").status_code == 200


def test_upload_into_a_folder(api):
    client, nc_files = api
    response = client.post(
        f"{BASE}/upload",
        files={"file": ("part.ngc", b"G1 X5\n", "text/plain")},
        data={"directory": "project/v2"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["filename"] == "project/v2/part.ngc"
    assert (nc_files / "project" / "v2" / "part.ngc").read_bytes() == b"G1 X5\n"

    escaped = client.post(
        f"{BASE}/upload",
        files={"file": ("x.ngc", b"G0\n", "text/plain")},
        data={"directory": "../outside"},
    )
    assert escaped.status_code == 400


def test_create_move_copy_folders(api):
    client, nc_files = api
    assert client.post(f"{BASE}/folder", json={"path": "job/rev1"}).status_code == 200
    assert (nc_files / "job" / "rev1").is_dir()
    assert client.post(f"{BASE}/folder", json={"path": "job"}).status_code == 409

    assert client.post(f"{BASE}/copy", json={"source": "project", "destination": "project-copy"}).status_code == 200
    assert (nc_files / "project-copy" / "v2" / "b.ngc").exists()

    assert client.put(f"{BASE}/rename", json={"source": "top.ngc", "destination": "job/top.ngc"}).status_code == 200
    assert (nc_files / "job" / "top.ngc").exists() and not (nc_files / "top.ngc").exists()

    into_itself = client.put(f"{BASE}/rename", json={"source": "project", "destination": "project/v2/p"})
    assert into_itself.status_code == 400


def test_delete_a_folder_with_content_needs_recursive(api):
    client, nc_files = api
    assert client.delete(f"{BASE}/project").status_code == 400
    assert (nc_files / "project" / "a.ngc").exists()

    assert client.delete(f"{BASE}/project/v2/b.ngc").status_code == 200
    assert client.delete(f"{BASE}/project", params={"recursive": "true"}).status_code == 200
    assert not (nc_files / "project").exists()


def test_the_unload_program_cannot_be_deleted(api):
    client, nc_files = api
    assert client.delete(f"{BASE}/EmptyProgram.ngc").status_code == 403
    assert (nc_files / "EmptyProgram.ngc").exists()
