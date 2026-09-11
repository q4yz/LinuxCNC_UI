"""A heater's auto-derived "fan" always shares its own `heater_pin`
(`hardware_json_generator._fan_payload` — real, documented, "every
generated machine has it": `test_halcompiler_validator.py::
test_heater_and_its_own_fan_sharing_a_pin_warns_but_does_not_block`).

Real bug this file guards against: `HalAssembler` never silently
merges a physical-pin collision without explicit permission via
`duplicate_pin_overrides` (`test_hal_assembler_duplicate_pin_override.py::
test_without_the_override_pin_the_merge_never_runs` — a deliberate
"trust the input" contract). Since the *compiler itself* is what
creates the heater/fan collision, the compiler has to be the one that
supplies that permission too — `build_hardware_json` now adds the
shared pin to `duplicate_pin_overrides` automatically. Without this, a
heater with no real declared cooling fan got two independent
`config.txt` `"PWM"` modules (two different `SP[i]` channels) pointing
at the exact same physical pin — invalid firmware, only ever caught by
actually loading a real generated machine.
"""

from __future__ import annotations

import json

from machineconfig_parser import MachineConfigParser
from services.halcompiler.assembler import HalAssembler
from services.machineconfig.hardware_json_generator import build_hardware_json

_CONFIG = """
[mcu]
connection: remora-spi

[stepper_x]
step_pin: PF13
dir_pin: PF12
rotation_distance: 40
position_max: 300

[extruder]
step_pin: PC13
dir_pin: PF0
rotation_distance: 33.5
heater_pin: PA2
sensor_type: Generic 3950
sensor_pin: PF4
control: pid
pid_Kp: 22.2
pid_Ki: 1.08
pid_Kd: 114
min_temp: 0
max_temp: 250

[heater_bed]
heater_pin: PA1
sensor_type: Generic 3950
sensor_pin: PF3
control: watermark
min_temp: 0
max_temp: 130

[estop]
"""


def _payload():
    graph = MachineConfigParser().parse_string(_CONFIG)
    return build_hardware_json(graph, "test")


def test_build_hardware_json_auto_allowlists_the_heater_fan_shared_pin():
    payload = _payload()
    assert "mcu:PA1" in payload["duplicate_pin_overrides"]
    assert "mcu:PA2" in payload["duplicate_pin_overrides"]


def test_assembler_emits_exactly_one_pwm_module_per_heater_pin():
    """The real regression: without the auto-override, this produced
    two `"PWM"` modules per heater (SP.0/SP.1 for the extruder,
    SP.2/SP.3 for the bed), both pointing at the same physical pin."""
    payload = _payload()
    fragment = HalAssembler(payload).assemble()
    config = json.loads(fragment.files["config_mcu.txt"])

    pwm_modules = [m for m in config["Modules"] if m["Type"] == "PWM"]
    pins = [m["PWM Pin"] for m in pwm_modules]
    assert len(pins) == len(set(pins)), f"a physical PWM pin was claimed twice: {pwm_modules}"
    assert sorted(pins) == ["PA_1", "PA_2"]


def test_heater_pid_output_and_its_placeholder_fan_collapse_onto_one_signal():
    payload = _payload()
    fragment = HalAssembler(payload).assemble()
    assert "net heater_extruder-heater-SP => remora.SP.0" in fragment.nets
    # The auto-fan's own signal name must not survive anywhere in the
    # output — it was folded into the heater's own signal.
    assert not any("fan_extruder-SP" in n for n in fragment.nets)
