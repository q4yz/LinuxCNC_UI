"""The host side of a remora-spi link, end to end: ``[mcu]`` keys in the
``.cfg`` -> ``hardware.json`` -> the ``remora-upload --sync`` and
``loadrt remora-spi`` lines in machine.hal (BTT CB1 example)."""
from __future__ import annotations

import json

import pytest

from MachineConfigParser import InvalidValueError, MachineConfigParser
from services.halcompiler import compile_machine_hal
from services.machineconfig.hardware_json_generator import build_hardware_json

CFG = """
[mcu]
connection: remora-spi
board: BTT MANTA M8P
SPI_freq: 1000000
PRU_base_freq: 40000
spi_cs_pin: PC10
reset_pin: PC12
{extra}

[machine]
kinematics: cartesian
max_velocity: 300
max_accel: 3000

[stepper_x]
step_pin: PF13
dir_pin: PF12
enable_pin: !PF14
position_endstop: 0
position_max: 200

[estop]
"""


def _payload(tmp_path, extra=""):
    cfg = tmp_path / "machine.cfg"
    cfg.write_text(CFG.format(extra=extra), encoding="utf-8")
    graph = MachineConfigParser().parse(cfg)
    return json.loads(json.dumps(build_hardware_json(graph, "cb1")))


def test_cb1_profile_compiles_to_the_sync_and_driver_lines(tmp_path):
    payload = _payload(tmp_path)
    mcu = payload["mcus"][0]
    assert (mcu["spi_cs_pin"], mcu["spi_freq"], mcu["reset_pin"]) == ("PC10", 1000000, "PC12")

    lines = compile_machine_hal(payload).splitlines()
    sync = "loadusr -w remora-upload --sync --spi-cs-pin PC10 -s 1000000 config_mcu.txt"
    driver = "loadrt remora-spi PRU_base_freq=40000 SPI_freq=1000000 spi_cs_pin=PC10 reset_pin=PC12"
    assert sync in lines and driver in lines
    assert lines.index(sync) < lines.index(driver)


def test_sync_config_false_drops_the_sync_line(tmp_path):
    text = compile_machine_hal(_payload(tmp_path, "sync_config: false"))
    assert "remora-upload" not in text
    assert "loadrt remora-spi" in text


def test_host_keys_are_rejected_on_other_connections(tmp_path):
    cfg = tmp_path / "machine.cfg"
    cfg.write_text("[mcu]\nconnection: parallelport\nspi_cs_pin: PC10\n", encoding="utf-8")
    with pytest.raises(InvalidValueError, match="spi_cs_pin"):
        MachineConfigParser().parse(cfg)


def test_sync_config_must_be_a_boolean(tmp_path):
    with pytest.raises(InvalidValueError, match="sync_config"):
        _payload(tmp_path, "sync_config: maybe")


def test_spi_freq_and_spi_clk_div_are_exclusive(tmp_path):
    with pytest.raises(InvalidValueError, match="SPI_clk_div"):
        _payload(tmp_path, "SPI_clk_div: 32")


def test_spi_clk_div_reaches_the_driver_line(tmp_path):
    cfg = tmp_path / "machine.cfg"
    cfg.write_text(
        CFG.format(extra="").replace("SPI_freq: 1000000\n", "SPI_clk_div: 32\n"), encoding="utf-8"
    )
    payload = json.loads(json.dumps(build_hardware_json(MachineConfigParser().parse(cfg), "pi4")))
    assert "SPI_clk_div=32" in compile_machine_hal(payload)


def test_board_reset_pin_stays_a_firmware_module_and_reset_pin_is_the_host_gpio(tmp_path):
    payload = _payload(tmp_path, "board_reset_pin: PC14")
    assert payload["mcus"][0]["board_reset_pin"] == "PC14"
    assert payload["mcus"][0]["reset_pin"] == "PC12"
    assert "reset_pin=PC12" in compile_machine_hal(payload)


def test_host_reset_pin_is_rejected_on_remora_eth(tmp_path):
    cfg = tmp_path / "machine.cfg"
    cfg.write_text("[mcu]\nconnection: remora-eth\nreset_pin: PC12\n", encoding="utf-8")
    with pytest.raises(InvalidValueError, match="reset_pin"):
        MachineConfigParser().parse(cfg)


def test_host_keys_are_spelled_like_the_driver_parameters(tmp_path):
    # Case-sensitive like pid_Kp: a lowercase spelling is a typo, not an alias.
    with pytest.raises(Exception, match="spi_freq"):
        _payload(tmp_path, "spi_freq: 2000000")


def test_estop_out_pin_on_a_remora_board_becomes_a_safe_output(tmp_path):
    cfg = tmp_path / "machine.cfg"
    cfg.write_text(
        CFG.format(extra="").replace("[estop]\n", "[estop]\nout_pin: !PB7\n"),
        encoding="utf-8",
    )
    payload = json.loads(json.dumps(build_hardware_json(MachineConfigParser().parse(cfg), "cb1")))

    from services.halcompiler.HalAssembler import HalAssembler
    fragment = HalAssembler(payload).assemble()
    assert "net user-enable-out => remora.output.00" in fragment.nets
    config = json.loads(fragment.files["config_mcu.txt"])
    out = next(m for m in config["Modules"] if m.get("Mode") == "Output")
    assert (out["Pin"], out["Safe State"], out["Invert"]) == ("PB_7", "Low", "True")


def test_out_safe_state_is_not_a_key(tmp_path):
    # Every output falls back to Low — not configurable.
    cfg = tmp_path / "machine.cfg"
    cfg.write_text(CFG.format(extra="").replace("[estop]\n", "[estop]\nout_safe_state: high\n"), encoding="utf-8")
    with pytest.raises(Exception, match="out_safe_state"):
        MachineConfigParser().parse(cfg)
