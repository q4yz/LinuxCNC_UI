"""`[tool_length_sensor]` — OR-ed with `[probe]` into `motion.probe-input`.

LinuxCNC has one probe input; the touch probe and the tool setter both
have to trip it. NC/NO is each pin's own `!`, resolved per input by the
MCU router (parport `-in-not`, Remora `.not`) before the OR.
"""

from __future__ import annotations

import pytest

from machineconfig_schema import SectionKind, schema_for_section
from MachineConfigParser import MachineConfigParser, UndefinedKeywordError
from models.machineconfig.HalFragmentModels import SERVO_THREAD, PinRole
from services.halcompiler import compile_machine_hal
from services.halcompiler.components.ProbeHalMapper import ProbeHalMapper
from services.machineconfig.hardware_json_generator import build_hardware_json


# -- parser / hardware.json ---------------------------------------------- #


def test_section_is_recognised_by_the_schema():
    assert schema_for_section("tool_length_sensor").kind is SectionKind.TOOL_LENGTH_SENSOR


def test_section_parses_its_pin():
    graph = MachineConfigParser().parse_string("[tool_length_sensor]\npin: !15\n")
    assert graph.tool_length_sensor.pin == "!15"


def test_absent_section_leaves_it_none():
    graph = MachineConfigParser().parse_string("[probe]\npin: 15\n")
    assert graph.tool_length_sensor is None


def test_unknown_keyword_raises():
    with pytest.raises(UndefinedKeywordError) as exc_info:
        MachineConfigParser().parse_string("[tool_length_sensor]\nbogus: 1\n")
    assert exc_info.value.section == "tool_length_sensor"


# -- mapper ---------------------------------------------------------------- #


def test_sensor_alone_drives_motion_probe_input_directly():
    fragment = ProbeHalMapper.to_fragment(None, {"pin": "!par0:15"})

    assert fragment.nets == ["net tool-length-sensor-in => motion.probe-input"]
    assert fragment.loadrt == []
    [request] = fragment.requests
    assert request.signal == "tool-length-sensor-in"
    assert request.role is PinRole.DIGITAL_IN
    assert request.pin.invert is True
    assert request.owner == "tool_length_sensor"


def test_probe_and_sensor_are_or_ed_into_motion_probe_input():
    fragment = ProbeHalMapper.to_fragment({"pin": "!par0:15"}, {"pin": "par0:13"})

    assert fragment.loadrt == ["loadrt or2 names=probe-or"]
    [addf] = fragment.addf
    assert (addf.func, addf.thread, addf.order) == ("probe-or", SERVO_THREAD, 0)
    assert fragment.nets == [
        "net probe-in => probe-or.in0",
        "net tool-length-sensor-in => probe-or.in1",
        "net probe-or-out probe-or.out => motion.probe-input",
    ]
    by_signal = {r.signal: r for r in fragment.requests}
    # Each switch keeps its own polarity (NC probe, NO tool setter).
    assert by_signal["probe-in"].pin.invert is True
    assert by_signal["tool-length-sensor-in"].pin.invert is False


def test_bare_sections_contribute_nothing():
    fragment = ProbeHalMapper.to_fragment({"pin": None}, {"pin": None})
    assert fragment.nets == [] and fragment.requests == [] and fragment.loadrt == []


# -- end to end: .cfg -> machine.hal --------------------------------------- #

_PARPORT = """
[mcu]
connection: parallelport

[stepper_x]
step_pin: 02
dir_pin: 03
rotation_distance: 40
position_max: 300

[estop]

[probe]
pin: !15

[tool_length_sensor]
pin: 13
"""

_REMORA = """
[mcu]
connection: remora-spi

[stepper_x]
step_pin: PF13
dir_pin: PF12
rotation_distance: 40
position_max: 300

[estop]

[probe]
pin: !PG6

[tool_length_sensor]
pin: PG9
"""


def _hal(config: str) -> str:
    payload = build_hardware_json(MachineConfigParser().parse_string(config), "test")
    return compile_machine_hal(payload)


def test_hardware_json_carries_the_sensor():
    payload = build_hardware_json(MachineConfigParser().parse_string(_PARPORT), "test")
    assert payload["tool_length_sensor"] == {"pin": "13"}
    assert payload["probe"] == {"pin": "!15"}


def test_parport_or_uses_the_router_specific_inverted_input():
    hal = _hal(_PARPORT)
    assert "loadrt or2 names=probe-or" in hal
    assert "addf probe-or servo-thread" in hal
    assert "net probe-or-out probe-or.out => motion.probe-input" in hal
    # `!15` -> the parport's own inverted input; `13` -> the plain one.
    assert "net probe-in <= parport.0.pin-15-in-not" in hal
    assert "net tool-length-sensor-in <= parport.0.pin-13-in" in hal
    assert "pin-13-in-not" not in hal


def test_remora_or_uses_the_router_specific_inverted_input():
    hal = _hal(_REMORA)
    assert "loadrt or2 names=probe-or" in hal
    # `!PG6` -> Remora's own inverted input; `PG9` -> the plain one.
    assert "net probe-in remora.input.00.not" in hal
    assert "net tool-length-sensor-in remora.input.01" in hal
    assert "remora.input.01.not" not in hal
