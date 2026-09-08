"""Tests for the file-scoped side of the Visual HAL editor endpoints.

``GET /api/v1/hal/layout?file=...`` and ``PUT /api/v1/hal/layout?file=...``
read/write real ``.hal`` files under an isolated ``MACHINES_DIR`` (same
isolation pattern as ``test_program_module.py``'s ``_isolated_program_root``)
so no test ever touches the real ``machine_config/machines/`` tree.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _isolated_machines_root(tmp_path: Path, monkeypatch) -> Path:
    from services import domain_file_services, reset_service_cache

    monkeypatch.setattr(domain_file_services.paths, "MACHINES_DIR", tmp_path)
    reset_service_cache()
    return tmp_path


def _app() -> FastAPI:
    from routers.hal import router as hal_router

    app = FastAPI()
    app.include_router(hal_router)
    return app


def _client() -> TestClient:
    return TestClient(_app())


def _write(root: Path, relative: str, content: str) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def test_get_layout_without_file_returns_empty_signals(monkeypatch, tmp_path):
    _isolated_machines_root(tmp_path, monkeypatch)
    client = _client()
    body = client.get("/api/v1/hal/layout").json()
    assert body["signals"] == []
    assert len(body["in_pins"]) > 0
    assert len(body["out_pins"]) > 0


def test_get_layout_with_file_parses_net_lines(monkeypatch, tmp_path):
    root = _isolated_machines_root(tmp_path, monkeypatch)
    _write(
        root,
        "example/custom.hal",
        "loadrt webgui\nnet spindle-on motion.spindle-on => webgui.spindle-on\n",
    )
    client = _client()
    body = client.get("/api/v1/hal/layout", params={"file": "example/custom.hal"}).json()
    assert len(body["signals"]) == 1
    signal = body["signals"][0]
    assert signal["name"] == "spindle-on"
    assert signal["source"]["full_name"] == "motion.spindle-on"
    assert [t["full_name"] for t in signal["targets"]] == ["webgui.spindle-on"]


def test_get_layout_unknown_pin_gets_placeholder(monkeypatch, tmp_path):
    root = _isolated_machines_root(tmp_path, monkeypatch)
    _write(
        root,
        "example/custom.hal",
        "net made-up some.unknown-pin => other.unknown-pin\n",
    )
    client = _client()
    body = client.get("/api/v1/hal/layout", params={"file": "example/custom.hal"}).json()
    signal = body["signals"][0]
    assert signal["source"]["full_name"] == "some.unknown-pin"
    assert "Not present" in signal["source"]["description"]
    assert signal["targets"][0]["full_name"] == "other.unknown-pin"


def test_get_layout_missing_file_returns_404(monkeypatch, tmp_path):
    _isolated_machines_root(tmp_path, monkeypatch)
    client = _client()
    response = client.get("/api/v1/hal/layout", params={"file": "nope/custom.hal"})
    assert response.status_code == 404


def test_get_layout_rejects_path_traversal(monkeypatch, tmp_path):
    _isolated_machines_root(tmp_path, monkeypatch)
    client = _client()
    response = client.get("/api/v1/hal/layout", params={"file": "../../etc/passwd"})
    assert response.status_code == 400


def test_save_layout_writes_delimited_block_and_preserves_rest(monkeypatch, tmp_path):
    root = _isolated_machines_root(tmp_path, monkeypatch)
    target = _write(
        root,
        "example/custom.hal",
        "loadrt webgui\naddf webgui.update servo-thread\n",
    )
    client = _client()
    response = client.put(
        "/api/v1/hal/layout",
        params={"file": "example/custom.hal"},
        json={"signals": [{"name": "spindle-on", "source": "motion.spindle-on", "targets": ["webgui.spindle-on"]}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["signals"][0]["name"] == "spindle-on"

    on_disk = target.read_text(encoding="utf-8")
    assert "loadrt webgui" in on_disk
    assert "addf webgui.update servo-thread" in on_disk
    assert "net spindle-on motion.spindle-on => webgui.spindle-on" in on_disk
    assert "AUTO-GENERATED" in on_disk


def test_save_layout_second_save_replaces_only_the_block(monkeypatch, tmp_path):
    root = _isolated_machines_root(tmp_path, monkeypatch)
    target = _write(root, "example/custom.hal", "loadrt webgui\n")
    client = _client()

    client.put(
        "/api/v1/hal/layout",
        params={"file": "example/custom.hal"},
        json={"signals": [{"name": "old-signal", "source": "a.pin", "targets": ["b.pin"]}]},
    )
    client.put(
        "/api/v1/hal/layout",
        params={"file": "example/custom.hal"},
        json={"signals": [{"name": "new-signal", "source": "c.pin", "targets": ["d.pin"]}]},
    )

    on_disk = target.read_text(encoding="utf-8")
    assert "old-signal" not in on_disk
    assert "new-signal" in on_disk
    assert on_disk.count("BEGIN VISUAL HAL EDITOR SIGNALS") == 1
    assert "loadrt webgui" in on_disk


def test_save_layout_missing_file_returns_404(monkeypatch, tmp_path):
    _isolated_machines_root(tmp_path, monkeypatch)
    client = _client()
    response = client.put(
        "/api/v1/hal/layout",
        params={"file": "nope/custom.hal"},
        json={"signals": []},
    )
    assert response.status_code == 404


def test_save_layout_rejects_path_traversal(monkeypatch, tmp_path):
    _isolated_machines_root(tmp_path, monkeypatch)
    client = _client()
    response = client.put(
        "/api/v1/hal/layout",
        params={"file": "../../etc/passwd"},
        json={"signals": []},
    )
    assert response.status_code == 400
