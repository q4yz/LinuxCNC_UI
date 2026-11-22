"""Uploads convert on a thread: the listing shows them as converting, then
the program; a failure stays listed with its message; the .ngc appears
whole (written aside and renamed)."""
from __future__ import annotations

import threading
import time

import pytest

import importlib

from domain_file_services.ProgramFileService import ProgramFileService

# the package re-exports the class under the module's name: the module itself
module = importlib.import_module("domain_file_services.ProgramFileService")

GCODE = b"G28\nG90\nM83\nG1 X10 Y10 E1 F600\n"


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "_CONVERSIONS", {})
    monkeypatch.setattr(ProgramFileService, "_machine_payload", staticmethod(lambda: None))
    return ProgramFileService(tmp_path)


def _wait(service, path, timeout=5.0):
    deadline = time.monotonic() + timeout
    while service.conversion_state(path) is not None and time.monotonic() < deadline:
        time.sleep(0.01)


def test_converting_then_listed(service, monkeypatch, tmp_path):
    gate = threading.Event()
    real = module.convert

    def slow_convert(*a, **k):
        gate.wait(5)
        return real(*a, **k)

    monkeypatch.setattr(module, "convert", slow_convert)
    stored = service.save_upload("parts/cube.gcode", GCODE, background=True)
    assert stored == "parts/cube.ngc"
    entry = next(f for f in service.list_program_files() if f.path == "parts/cube.ngc")
    assert entry.status == "converting" and entry.parent == "parts"
    with pytest.raises(FileExistsError, match="still being converted"):
        service.save_upload("parts/cube.gcode", GCODE, background=True)
    assert not (tmp_path / "parts" / "cube.ngc").exists()
    gate.set()
    _wait(service, stored)
    entry = next(f for f in service.list_program_files() if f.path == "parts/cube.ngc")
    assert entry.status is None and entry.size_bytes > 0
    assert "LINUXCNC_UI_PRESTART" in (tmp_path / "parts" / "cube.ngc").read_text()
    assert not any(p.name.endswith(".part") for p in tmp_path.rglob("*"))


def test_a_failed_conversion_is_listed(service, monkeypatch):
    def broken(*a, **k):
        raise ValueError("bad G-code")

    monkeypatch.setattr(module, "convert", broken)
    stored = service.save_upload("bad.gcode", GCODE, background=True)
    deadline = time.monotonic() + 5
    while (service.conversion_state(stored) or {}).get("error") is None and time.monotonic() < deadline:
        time.sleep(0.01)
    entry = next(f for f in service.list_program_files() if f.path == "bad.ngc")
    assert entry.status == "failed" and entry.message == "bad G-code"
    monkeypatch.setattr(module, "convert", module.__dict__["convert"])  # a retry is allowed after a failure
    monkeypatch.setattr(module, "FAILED_SHOWN_S", -1.0)
    assert not any(f.path == "bad.ngc" for f in service.list_program_files())  # shown for a while only


def test_synchronous_upload_unchanged(service, tmp_path):
    assert service.save_upload("x.gcode", GCODE) == "x.ngc"
    assert (tmp_path / "x.ngc").exists() and service.conversion_state("x.ngc") is None
    assert service.save_upload("y.ngc", b"G0 X1\nM2\n", background=True) == "y.ngc"  # no conversion
    assert (tmp_path / "y.ngc").read_bytes() == b"G0 X1\nM2\n"
