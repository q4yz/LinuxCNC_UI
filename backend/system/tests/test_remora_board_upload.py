"""Manual "Upload to board" of config_<mcu>.txt / firmware.bin
(services/RemoraBoardUploader.py, MachineLifecycleService.upload_to_board,
POST /modules/machineconfig/machines/board-upload). ``remora-upload`` is faked."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import services.MachineLifecycleService as mls_module
import services.RemoraBoardUploader as uploader_module
from exceptions import BadRequestError, ConflictError
from services.MachineLifecycleService import MachineLifecycleService
from services.RemoraBoardUploader import RemoraBoardUploader, is_board_file

CB1_MCU = {"id": "mcu", "connection": "remora-spi", "spi_cs_pin": "PC10", "spi_freq": 1000000}


class _Tool(list[list[str]]):
    """Fake ``remora-upload``: the argv it was called with, plus its result."""

    def __init__(self) -> None:
        super().__init__()
        self.result = SimpleNamespace(returncode=0, stdout="config.txt written and verified on the SD card", stderr="")

    def run(self, cmd, **kwargs):
        self.append(cmd)
        return self.result


@pytest.fixture()
def tool(monkeypatch):
    fake = _Tool()
    monkeypatch.setattr(uploader_module.subprocess, "run", fake.run)
    return fake


@pytest.fixture()
def configs(tmp_path):
    (tmp_path / "hardware.json").write_text(json.dumps({"mcus": [CB1_MCU]}), encoding="utf-8")
    (tmp_path / "config_mcu.txt").write_text("{}", encoding="utf-8")
    (tmp_path / "firmware.bin").write_bytes(b"\0" * 2048)
    return tmp_path


@pytest.mark.parametrize("name, ok", [
    ("config_mcu.txt", True), ("config_board_a.txt", True), ("firmware.bin", True),
    ("config.txt", False), ("machine.hal", False), ("firmware.bin.bak", False),
])
def test_is_board_file(name, ok):
    assert is_board_file(name) is ok


def test_config_goes_up_as_config_txt_over_the_machines_link(configs, tool):
    RemoraBoardUploader(tool="remora-upload").upload(configs / "config_mcu.txt")
    assert tool == [["remora-upload", "--spi-cs-pin", "PC10", "-s", "1000000",
                     "-n", "config.txt", str(configs / "config_mcu.txt")]]


def test_firmware_goes_up_as_firmware_bin(configs, tool):
    RemoraBoardUploader(tool="remora-upload").upload(configs / "firmware.bin")
    assert tool[0][-3:] == ["-n", "firmware.bin", str(configs / "firmware.bin")]


def test_a_failed_upload_reports_the_tool_output(configs, tool):
    tool.result.returncode = 1
    tool.result.stdout = "no answer from the board"
    with pytest.raises(BadRequestError, match="no answer from the board"):
        RemoraBoardUploader(tool="remora-upload").upload(configs / "config_mcu.txt")


def test_config_for_an_unknown_mcu_is_rejected(configs, tool):
    (configs / "config_other.txt").write_text("{}", encoding="utf-8")
    with pytest.raises(BadRequestError, match="other"):
        RemoraBoardUploader(tool="remora-upload").upload(configs / "config_other.txt")
    assert tool == []


def test_missing_tool_says_how_to_install_it(configs, tool):
    uploader = RemoraBoardUploader(tool="remora-upload")
    uploader._tool = None
    with pytest.raises(BadRequestError, match="install_hal_components"):
        uploader.upload(configs / "config_mcu.txt")


def test_upload_is_refused_while_linuxcnc_runs(configs, tool, monkeypatch):
    monkeypatch.setattr(mls_module, "linuxcnc_pids", lambda: [4242])
    with pytest.raises(ConflictError, match="Stop LinuxCNC"):
        MachineLifecycleService().upload_to_board(configs / "config_mcu.txt")
    assert tool == []


def test_upload_and_start_exclude_each_other(configs, monkeypatch):
    service = MachineLifecycleService()
    monkeypatch.setattr(mls_module, "linuxcnc_pids", lambda: [])

    def slow_upload(self, file):
        # A start arriving now must get a 409, not grab the SPI link.
        with pytest.raises(ConflictError, match="uploading"):
            service.start()
        return "ok"

    monkeypatch.setattr(mls_module.RemoraBoardUploader, "upload", slow_upload)
    assert service.upload_to_board(configs / "config_mcu.txt") == "ok"
