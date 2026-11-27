"""[ace] (the ACE Pro): parsing, hardware.json, the INI, HAL and the NGC."""
from __future__ import annotations

from pathlib import Path

import pytest
from core import ace_contract
from MachineConfigParser import (
    InvalidValueError,
    MachineConfigParser,
    MissingRequiredKeywordError,
)
from models.machineconfig.HardwareRecords import HardwareRecords
from services.halcompiler import render_webgui_connections
from services.machineconfig import AxisBuilder, AxisMappingPolicy
from services.machineconfig.hardware_json_generator import build_hardware_json
from services.machinetemplates.ini_template_generator import render_ini_template

PRINTER = open("tests/fixtures/profiles/full_klipper.cfg").read()
SENSORS = "\n[input_pin toolhead_filament]\npin: ^PG11\n\n[input_pin ace_hub]\npin: ^PG12\n"
ACE = "\n[ace]\ntoolhead_sensor: toolhead_filament\nhub_sensor: ace_hub\nbowden_length: 900\n"
CUTTER = "cutter_start_x: 250\ncutter_start_y: 10\ncutter_end_x: 265\ncutter_end_y: 10\n"
M_CODES = Path(__file__).resolve().parents[3] / "machine_config" / "m_codes"


def _graph(cfg: str):
    return MachineConfigParser().parse_string(cfg)


def _payload(cfg: str):
    return build_hardware_json(_graph(cfg), "m")


def test_ace_reaches_hardware_json_with_defaults():
    ace = _payload(PRINTER + SENSORS + ACE + CUTTER)["ace"]
    assert ace["serial"] == "/dev/serial/by-id/usb-ANYCUBIC_ACE_1-if00"
    assert ace["toolhead_sensor"] == "toolhead_filament" and ace["hub_sensor"] == "ace_hub"
    assert ace["bowden_length"] == 900.0 and ace["unload_length"] == 950.0  # bowden + 50
    assert ace["park_x"] == 0.0 and ace["park_y"] == 0.0  # the X / Y minimum
    assert ace["cutter"] is True and ace["cutter_end_x"] == 265.0
    assert HardwareRecords.ace(_payload(PRINTER + SENSORS + ACE + CUTTER)).cut_retract == 30.0
    # no [ace]: nothing; no cutter positions: no cut
    assert _payload(PRINTER).get("ace") is None
    assert _payload(PRINTER + SENSORS + ACE)["ace"]["cutter"] is False


@pytest.mark.parametrize("extra, error", [
    ("", MissingRequiredKeywordError),                                   # toolhead_sensor missing
    ("toolhead_sensor: nope\n", InvalidValueError),                      # not an [input_pin]
    ("toolhead_sensor: toolhead_filament\nhub_sensor: nope\n", InvalidValueError),
    ("toolhead_sensor: toolhead_filament\nfeed_speed: 0\n", InvalidValueError),
    ("toolhead_sensor: toolhead_filament\nz_lift: -1\n", InvalidValueError),
    ("toolhead_sensor: toolhead_filament\ncutter_start_x: 1\n", InvalidValueError),  # half a cutter
    ("toolhead_sensor: toolhead_filament\napproach_length: 2000\n", InvalidValueError),
])
def test_bad_ace_sections(extra, error):
    with pytest.raises(error):
        _graph(PRINTER + SENSORS + "\n[ace]\n" + extra)


def test_negative_positions_are_fine():
    ace = _payload(PRINTER + SENSORS + ACE + "park_x: -5\n" + CUTTER.replace("250", "-3"))["ace"]
    assert ace["park_x"] == -5.0 and ace["cutter_start_x"] == -3.0


def test_ini_gets_the_m640_remap_and_the_ngc_values():
    graph = _graph(PRINTER + SENSORS + ACE + CUTTER)
    payload = build_hardware_json(graph, "m")
    axes = AxisBuilder(graph, policy=AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS).build()
    ini = render_ini_template("m", axes, payload["tools"], remaps=[ace_contract.REMAP],
                              ace=HardwareRecords.ace(payload))
    assert "REMAP=M640 modalgroup=10 argspec=P ngc=ace_change" in ini
    section = ini.split("[ACE]", 1)[1].split("\n\n", 1)[0]
    assert "\nCUTTER = 1" in section and "\nCUTTER_END_X = 265" in section
    assert f"\nREQUEST_OUTPUT = {ace_contract.REQUEST_DOUT}" in section
    assert f"\nDONE_INPUT = {ace_contract.DONE_DIN}" in section and f"\nERROR_INPUT = {ace_contract.ERROR_DIN}" in section


def test_hal_nets_the_handshake():
    hal = render_webgui_connections(_payload(PRINTER + SENSORS + ACE))
    assert f"net ace-request motion.digital-out-0{ace_contract.REQUEST_DOUT} => webgui.ace-request" in hal
    assert f"net ace-slot motion.analog-out-0{ace_contract.SLOT_AOUT} => webgui.ace-slot" in hal
    assert f"net ace-done webgui.ace-done => motion.digital-in-0{ace_contract.DONE_DIN}" in hal
    assert f"net ace-error webgui.ace-error => motion.digital-in-0{ace_contract.ERROR_DIN}" in hal
    # the sensors are ordinary input pins the backend reads
    assert "net toolhead_filament-in => webgui.toolhead_filament" in hal
    assert "ace-request" not in render_webgui_connections(_payload(PRINTER))


def test_ace_change_ngc_reads_every_ini_value_and_the_handshake():
    ngc = (M_CODES / "ace_change.ngc").read_text()
    assert ngc.startswith("; ace_change.ngc") and "o<ace_change> sub" in ngc and "o<ace_change> endsub" in ngc
    keys = ("PARK_X", "PARK_Y", "Z_LIFT", "CUTTER", "CUTTER_START_X", "CUTTER_START_Y", "CUTTER_END_X",
            "CUTTER_END_Y", "CUTTER_SPEED", "CUT_RETRACT", "SENSOR_TO_NOZZLE", "LOAD_SPEED", "PURGE_LENGTH",
            "PURGE_SPEED", "TIMEOUT", "REQUEST_OUTPUT", "SLOT_OUTPUT", "DONE_INPUT", "ERROR_INPUT")
    for key in keys:
        assert f"#<_ini[ACE]{key}>" in ngc, key
    assert f"#<_hal[webgui.{ace_contract.PIN_CURRENT}]>" in ngc
    # request up, wait for done, read error, request down; a failure pauses and retries
    assert ngc.index("M64 P") < ngc.index("M66 P#<_ini[ACE]DONE_INPUT> L3") < ngc.index("M65 P")
    assert "o<try> while" in ngc and "M0" in ngc
    assert "G92 A#<a>" in ngc and "M70" in ngc and "M72" in ngc


def test_a_machine_with_an_ace_generates(tmp_path):
    """The whole generation: compiles, validates, and writes the REMAP, the
    [ACE] section and the handshake nets."""
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import generate_machine_templates

    profiles, machines = tmp_path / "profiles", tmp_path / "machines"
    profiles.mkdir()
    machines.mkdir()
    (profiles / "printer.cfg").write_text(PRINTER + SENSORS + ACE + CUTTER, encoding="utf-8")
    generate_machine_templates("printer.cfg", config_service=ConfigFileService(root=profiles),
                               machine_service=MachineFileService(root=machines))
    configs = machines / "printer" / "configs"
    ini = (configs / "machine.ini").read_text(encoding="utf-8")
    assert ace_contract.REMAP in ini and "[ACE]" in ini
    assert "net ace-done webgui.ace-done" in (configs / "webgui_connections.hal").read_text(encoding="utf-8")
