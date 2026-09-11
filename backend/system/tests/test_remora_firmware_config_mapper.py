"""RemoraFirmwareConfigMapper — the `{"Board", "Modules"}` root shape.

Pulled out of `HalAssembler._render_firmware_configs` so the assembler
only decides *which* modules belong to *which* MCU, not the firmware
target's own root JSON shape (`.agent/component/mcu_spi_remora.md`).
"""

from __future__ import annotations

from services.halcompiler.components.RemoraFirmwareConfigMapper import (
    DEFAULT_FIRMWARE_BOARD,
    RemoraFirmwareConfigMapper,
)


def test_uses_the_declared_board_name():
    config = RemoraFirmwareConfigMapper.to_config({"board": "SKR v1.4"}, [])
    assert config["Board"] == "SKR v1.4"


def test_falls_back_to_the_documented_default_board():
    """Matches the real, working `machine_config/example/ender3/config.txt`."""
    config = RemoraFirmwareConfigMapper.to_config({}, [])
    assert config["Board"] == DEFAULT_FIRMWARE_BOARD == "BIGTREETECH OCTOPUS"


def test_modules_pass_through_unmodified_and_in_order():
    modules = [{"Name": "a"}, {"Name": "b"}]
    config = RemoraFirmwareConfigMapper.to_config({}, modules)
    assert config["Modules"] == modules


def test_root_has_no_top_level_thread_key():
    """The real reference config has no frequency block — an earlier,
    unverified draft of this compiler invented one."""
    config = RemoraFirmwareConfigMapper.to_config({}, [])
    assert "Thread" not in config
    assert set(config.keys()) == {"Board", "Modules"}
