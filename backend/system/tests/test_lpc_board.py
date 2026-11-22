"""An LPC1768 / LPC1769 board, end to end: ``[mcu] board`` -> the derived
``chip`` in ``hardware.json`` -> ``loadrt remora_lpc`` and no SD-card
config sync in machine.hal."""
from __future__ import annotations

import json
from typing import Any

import pytest

from MachineConfigParser import MachineConfigParser, chip_for_board
from services.halcompiler import compile_machine_hal
from services.machineconfig.hardware_json_generator import build_hardware_json

CFG = """
[mcu]
connection: remora-spi
{board}

[machine]
kinematics: cartesian
max_velocity: 300
max_accel: 3000

[stepper_x]
step_pin: P2.2
dir_pin: P2.6
enable_pin: !P2.1
position_endstop: 0
position_max: 200

[estop]
"""


def _payload(board: str) -> dict[str, Any]:
    graph = MachineConfigParser().parse_string(CFG.format(board=f"board: {board}" if board else ""))
    return json.loads(json.dumps(build_hardware_json(graph, "skr")))


@pytest.mark.parametrize("board", [
    "BIGTREETECH SKR v1.3 & v1.4",   # Remora's own config.txt name
    "BIGTREETECH SKR v1.4",
    "BTT SKR V1.4 Turbo",
    "SKR 1.3",
    "MKS SBASE v1.3",
    "MKS SGEN_L",
    "Smoothieboard",
    "Re-ARM",
    "Azteeg X5 Mini",
    "LPC1769",
])
def test_lpc_boards(board):
    assert chip_for_board(board) == "lpc17xx"


@pytest.mark.parametrize("board", [
    "BIGTREETECH SKR v2", "BIGTREETECH SKR v3", "BTT SKR Mini E3 V3", "SKR Pro 1.2",
    "BIGTREETECH MANTA M8P V1.0 / V1.1", "BIGTREETECH OCTOPUS", "MKS MONSTER8", "FYSETC SPIDER",
    "Mks Robin E3", None, "",
])
def test_stm32_and_unknown_boards(board):
    assert chip_for_board(board) is None


def test_an_skr_1_4_loads_remora_lpc_without_a_config_sync():
    payload = _payload("BIGTREETECH SKR v1.4")
    assert payload["mcus"][0]["chip"] == "lpc17xx"
    lines = compile_machine_hal(payload).splitlines()
    assert "loadrt remora_lpc" in lines
    assert not any(line.startswith("loadrt remora-spi") for line in lines)
    assert not any("remora-upload" in line for line in lines)


def test_an_stm32_board_stays_remora_spi_with_its_sync():
    payload = _payload("BIGTREETECH MANTA M8P V1.0 / V1.1")
    assert "chip" not in payload["mcus"][0]
    lines = compile_machine_hal(payload).splitlines()
    assert any(line.startswith("loadrt remora-spi") for line in lines)
    assert any("remora-upload --sync" in line for line in lines)


def test_no_board_is_stm32():
    assert "chip" not in _payload("")["mcus"][0]
