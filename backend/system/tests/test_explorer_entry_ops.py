"""Profiles / machines explorer entry actions: copy, move, (recursive) delete."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_file_services.FileService import FileService


@pytest.fixture()
def service(tmp_path) -> FileService:
    root = tmp_path / "root"
    (root / "folder" / "sub").mkdir(parents=True)
    (root / "folder" / "a.cfg").write_text("A", encoding="utf-8")
    (root / "folder" / "sub" / "b.hal").write_text("B", encoding="utf-8")
    (root / "single.cfg").write_text("S", encoding="utf-8")
    return FileService(root)


# -- FileService ------------------------------------------------------------ #


def test_delete_of_a_folder_with_content_needs_recursive(service):
    with pytest.raises(IsADirectoryError):
        service.delete("folder")
    assert (service.root / "folder" / "a.cfg").exists()

    service.delete("folder", recursive=True)
    assert not (service.root / "folder").exists()


def test_the_root_itself_is_never_deleted(service):
    for path in ("", ".", "folder/.."):
        with pytest.raises(ValueError):
            service.delete(path, recursive=True)
    assert service.root.exists()


def test_copy_a_file_and_a_whole_folder(service):
    service.copy("single.cfg", "copies/single-copy.cfg")
    assert (service.root / "copies" / "single-copy.cfg").read_text(encoding="utf-8") == "S"

    service.copy("folder", "folder-copy")
    assert (service.root / "folder-copy" / "sub" / "b.hal").read_text(encoding="utf-8") == "B"
    assert (service.root / "folder" / "a.cfg").exists(), "the source stays"


def test_copy_never_overwrites_and_never_nests_into_itself(service):
    with pytest.raises(FileExistsError):
        service.copy("single.cfg", "folder/a.cfg")
    with pytest.raises(ValueError):
        service.copy("folder", "folder/sub/again")
    with pytest.raises(FileNotFoundError):
        service.copy("missing.cfg", "x.cfg")


def test_move_a_folder_into_itself_is_refused(service):
    with pytest.raises(ValueError):
        service.rename("folder", "folder/sub/moved")
    service.rename("folder", "elsewhere/folder")
    assert (service.root / "elsewhere" / "folder" / "sub" / "b.hal").exists()


# -- HTTP ------------------------------------------------------------------- #


@pytest.fixture()
def client(monkeypatch, tmp_path):
    from services import domain_file_services, reset_service_cache
    from routers import machineconfig

    mc = tmp_path / "machine_config"
    profiles, machines = mc / "profiles", mc / "machines"
    (profiles / "dir").mkdir(parents=True)
    (profiles / "dir" / "p.cfg").write_text("P", encoding="utf-8")
    (machines / "m1" / "configs").mkdir(parents=True)
    (machines / "m1" / "configs" / "machine.hal").write_text("H", encoding="utf-8")

    paths_mod = domain_file_services.paths
    monkeypatch.setattr(paths_mod, "MACHINE_CONFIG_DIR", mc)
    monkeypatch.setattr(paths_mod, "PROFILES_DIR", profiles)
    monkeypatch.setattr(paths_mod, "MACHINES_DIR", machines)
    reset_service_cache()
    app = FastAPI()
    app.include_router(machineconfig.router)
    yield TestClient(app), profiles, machines
    reset_service_cache()


BASE = "/api/v1/modules/machineconfig"


@pytest.mark.parametrize("root", ["profiles", "machines"])
def test_copy_endpoint(client, root):
    test_client, profiles, machines = client
    source = "dir" if root == "profiles" else "m1"
    response = test_client.post(f"{BASE}/{root}/copy", json={"source": source, "destination": f"{source}-copy"})
    assert response.status_code == 200, response.text
    base = profiles if root == "profiles" else machines
    assert (base / f"{source}-copy").is_dir()

    again = test_client.post(f"{BASE}/{root}/copy", json={"source": source, "destination": f"{source}-copy"})
    assert again.status_code == 409


@pytest.mark.parametrize("root", ["profiles", "machines"])
def test_delete_endpoint_needs_recursive_for_a_folder_with_content(client, root):
    test_client, profiles, machines = client
    target = "dir" if root == "profiles" else "m1"
    base = profiles if root == "profiles" else machines

    refused = test_client.delete(f"{BASE}/{root}/entry", params={"path": target})
    assert refused.status_code == 400
    assert (base / target).exists()

    deleted = test_client.delete(f"{BASE}/{root}/entry", params={"path": target, "recursive": "true"})
    assert deleted.status_code == 200, deleted.text
    assert not (base / target).exists()
