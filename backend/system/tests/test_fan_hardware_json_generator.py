"""``fans[]`` payload building — `[fan]` (kind: "part") and
`[heater_fan]` (kind: "heater") both land in the same list
(`.agent/component/fan.md`), discriminated by `kind`.
"""

from __future__ import annotations

from machineconfig_parser import MachineConfigParser
from services.machineconfig.hardware_json_generator import build_hardware_json

_BASE_HEATER = """
[mcu]
connection: remora-spi

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

[estop]
"""


def _fans_by_id(cfg: str) -> dict[str, dict[str, object]]:
    graph = MachineConfigParser().parse_string(cfg)
    payload = build_hardware_json(graph, "test")
    return {f["id"]: f for f in payload["fans"]}


def test_standalone_fan_gets_kind_part():
    fans = _fans_by_id(_BASE_HEATER + "\n[fan]\npin: PA8\n")
    assert fans["fan"]["kind"] == "part"
    assert fans["fan"]["pin"] == "PA8"


def test_standalone_fan_carries_max_power_and_shutdown_speed_when_set():
    fans = _fans_by_id(
        _BASE_HEATER + "\n[fan]\npin: PA8\nmax_power: 0.5\nshutdown_speed: 0.1\n"
    )
    assert fans["fan"]["max_power"] == 0.5
    assert fans["fan"]["shutdown_speed"] == 0.1


def test_standalone_fan_omits_unset_optional_fields():
    fans = _fans_by_id(_BASE_HEATER + "\n[fan]\npin: PA8\n")
    assert "max_power" not in fans["fan"]
    assert "shutdown_speed" not in fans["fan"]


def test_heater_own_auto_derived_fan_also_gets_kind_part():
    """The heater's own placeholder (sharing its heater_pin) is a
    "part" fan too — the operator can still command it (it's the same
    physical pin the PID output already drives, but the discriminator
    stays consistent with every other part fan)."""
    fans = _fans_by_id(_BASE_HEATER)
    assert fans["fan_extruder"]["kind"] == "part"


def test_heater_fan_gets_kind_heater_and_resolves_its_heater_reference():
    """``heater: extruder`` (Klipper's raw section name) resolves to
    this compiler's canonical tool id, ``heater_extruder`` — the same
    resolution every other heater cross-reference in this file goes
    through."""
    fans = _fans_by_id(
        _BASE_HEATER
        + "\n[heater_fan heatbreak_cooling_fan]\npin: PA9\nheater: extruder\n"
        "heater_temp: 60\nfan_speed: 0.8\n"
    )
    fan = fans["heater_fan_heatbreak_cooling_fan"]
    assert fan["kind"] == "heater"
    assert fan["heater"] == "heater_extruder"
    assert fan["heater_temp"] == 60.0
    assert fan["fan_speed"] == 0.8


def test_heater_fan_referencing_a_heated_bed_resolves_the_full_section_name():
    """A heated bed's own Klipper section name IS its canonical id
    already (``heater_bed``, not ``bed``) — ``_heater_id`` must pass
    it through unchanged, not double-prefix it."""
    cfg = (
        "[mcu]\nconnection: remora-spi\n\n"
        "[heater_bed]\nheater_pin: PA1\nsensor_type: Generic 3950\n"
        "sensor_pin: PF3\ncontrol: watermark\nmin_temp: 0\nmax_temp: 130\n\n"
        "[heater_fan bed_fan]\npin: PA9\nheater: heater_bed\n\n"
        "[estop]\n"
    )
    fans = _fans_by_id(cfg)
    assert fans["heater_fan_bed_fan"]["heater"] == "heater_bed"


def test_heater_fan_omits_unset_optional_fields():
    fans = _fans_by_id(
        _BASE_HEATER + "\n[heater_fan heatbreak_cooling_fan]\npin: PA9\n"
    )
    fan = fans["heater_fan_heatbreak_cooling_fan"]
    assert "heater_temp" not in fan
    assert "fan_speed" not in fan
    assert "max_power" not in fan
    assert "shutdown_speed" not in fan
    # heater always has a value (Klipper's own default, "extruder").
    assert fan["heater"] == "heater_extruder"
