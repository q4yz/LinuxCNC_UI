"""The compile gate: every rule reports, nothing raises.

One diagnostic per real fault, all collected in a single pass — see
``.agent/component/README.md`` § 3. Each test starts from a machine
that validates cleanly and breaks exactly one thing, so a failure here
names the rule that regressed.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from services.halcompiler import MachineValidator, validate_machine

REPO_ROOT = Path(__file__).resolve().parents[3]


def _codes(payload) -> set[str]:
    return {d.code for d in validate_machine(payload)}


@pytest.fixture()
def machine() -> dict[str, object]:
    """A minimal machine that validates clean."""
    return {
        "version": "2.2",
        "machine": "t",
        "source": "test",
        "kinematics": "cartesian",
        "hal_type": "remora",
        "mcus": [{"id": "mcu", "connection": "remora-spi"}],
        "axes": [
            {
                "id": "x",
                "joint_numbers": [0],
                "endstop": "endstop_x_min",
                "position_min": 0.0,
                "position_max": 200.0,
                "position_endstop": 0.0,
            }
        ],
        "joints": [
            {
                "id": "stepper_x",
                "joint_number": 0,
                "driver": "driver_stepper_x",
                "step_pin": "PF13",
                "dir_pin": "PF12",
                "enable_pin": "!PF14",
            }
        ],
        "drivers": [{"id": "driver_stepper_x", "type": "TMC2209"}],
        "endstops": [{"id": "endstop_x_min", "pin": "^PC0"}],
        "temperature_sensors": [{"id": "bed", "pin": "PA0"}],
        "fans": [{"id": "fan_heater_bed", "pin": "PB1"}],
        "tools": [
            {
                "id": "heater_bed",
                "type": "heated_bed",
                "sensor": "bed",
                "fan": "fan_heater_bed",
                "heater_pin": "PB7",
                "min_temp": 0.0,
                "max_temp": 130.0,
            }
        ],
    }


def test_a_clean_machine_reports_nothing(machine):
    assert validate_machine(machine) == []


def test_nothing_raises_even_on_nonsense():
    """The gate reports; it never explodes on bad input."""
    assert MachineValidator.has_errors(validate_machine({}))


# -- referential ------------------------------------------------------- #


def test_unknown_mcu(machine):
    machine["joints"][0]["step_pin"] = "nosuch:02"
    assert "E_UNKNOWN_MCU" in _codes(machine)


def test_missing_default_mcu(machine):
    """A bare pin needs an MCU literally named "mcu"."""
    machine["mcus"][0]["id"] = "board0"
    assert "E_NO_DEFAULT_MCU" in _codes(machine)


def test_unknown_sensor_and_fan(machine):
    machine["tools"][0]["sensor"] = "ghost"
    machine["tools"][0]["fan"] = "ghost_fan"
    codes = _codes(machine)
    assert {"E_UNKNOWN_SENSOR", "E_UNKNOWN_FAN"} <= codes


def test_unknown_driver_and_endstop(machine):
    machine["joints"][0]["driver"] = "ghost"
    machine["axes"][0]["endstop"] = "ghost"
    assert _codes(machine) == {"E_UNKNOWN_REF"}


def test_pin_conflict(machine):
    machine["joints"][0]["dir_pin"] = "PF13"  # already the step pin
    assert "E_PIN_CONFLICT" in _codes(machine)


def test_malformed_pin(machine):
    machine["joints"][0]["step_pin"] = "mcu:"
    assert "E_MALFORMED_PIN" in _codes(machine)


def test_estop_pins_are_checked_for_unknown_mcu(machine):
    """`estop` is a top-level singleton, not a list — it needs its own
    fold into `_parsed_pins()` to get the same generic checks every
    other pin field gets for free."""
    machine["estop"] = {"fault_pin": "nosuch:10"}
    assert "E_UNKNOWN_MCU" in _codes(machine)


def test_estop_pins_participate_in_pin_conflict_detection(machine):
    machine["estop"] = {"out_pin": "PF13"}  # already the joint's step pin
    assert "E_PIN_CONFLICT" in _codes(machine)


def test_estop_malformed_pin_is_reported(machine):
    machine["estop"] = {"fault_pin": "mcu:"}
    assert "E_MALFORMED_PIN" in _codes(machine)


def test_estop_absent_key_is_not_an_error():
    """No presence/cardinality rule lives here — that's
    `build_hardware_json`'s job (`test_machineconfig_module.py`), not
    the compile-gate validator's. A payload with no `estop` key
    at all (e.g. a fixture predating this feature) must still
    validate exactly as it did before."""
    machine = {
        "version": "2.2",
        "machine": "t",
        "source": "test",
        "kinematics": "cartesian",
        "hal_type": "remora",
        "mcus": [{"id": "mcu", "connection": "remora-spi"}],
    }
    assert validate_machine(machine) == []


def test_estop_with_only_valid_pins_reports_nothing(machine):
    machine["estop"] = {"fault_pin": "PG6", "out_pin": "PG7"}
    assert _codes(machine) == set()


def test_duplicate_pin_override_suppresses_the_conflict(machine):
    """An operator-declared exception — see `[duplicate_pin_override]`."""
    machine["joints"][0]["dir_pin"] = "PF13"  # already the step pin
    machine["duplicate_pin_overrides"] = ["mcu:PF13"]
    assert "E_PIN_CONFLICT" not in _codes(machine)


def test_duplicate_pin_override_only_covers_the_listed_pin(machine):
    """Not a global bypass — an unrelated conflict still blocks."""
    machine["joints"][0]["dir_pin"] = "PF13"
    machine["endstops"][0]["pin"] = "PF13"  # a third, different claim
    machine["duplicate_pin_overrides"] = ["mcu:PF14"]  # some other pin
    assert "E_PIN_CONFLICT" in _codes(machine)


def test_heater_and_its_own_fan_sharing_a_pin_warns_but_does_not_block(machine):
    """The generator derives the fan pin from the heater's own pin.

    Real (one output cannot do both) but not the operator's mistake, so
    it must not stop the compile — every generated machine has it.
    """
    machine["fans"][0]["pin"] = machine["tools"][0]["heater_pin"]
    diagnostics = validate_machine(machine)
    assert [d.code for d in diagnostics] == ["W_FAN_SHARES_HEATER_PIN"]
    assert not MachineValidator.has_errors(diagnostics)


# -- motion ------------------------------------------------------------ #


def test_motion_on_an_io_only_mcu(machine):
    machine["mcus"][0]["connection"] = "rs485"
    assert "E_MOTION_ON_IO_MCU" in _codes(machine)


def test_mixed_motion_classes(machine):
    machine["mcus"].append({"id": "par0", "connection": "parallelport"})
    machine["joints"].append(
        {
            "id": "stepper_y",
            "joint_number": 1,
            "driver": "driver_stepper_x",
            "step_pin": "par0:02",
        }
    )
    machine["axes"].append({"id": "y", "joint_numbers": [1]})
    assert "E_MIXED_MOTION_CLASS" in _codes(machine)


def test_unknown_capability_class(machine):
    machine["mcus"][0]["connection"] = "brand-new-bus"
    assert "E_UNKNOWN_MCU_CLASS" in _codes(machine)


def test_joint_numbering_must_be_dense(machine):
    machine["joints"][0]["joint_number"] = 3
    assert "E_JOINT_NUMBERING" in _codes(machine)


def test_axis_without_a_joint(machine):
    machine["axes"][0]["joint_numbers"] = []
    assert "E_AXIS_WITHOUT_JOINT" in _codes(machine)


# -- ranges ------------------------------------------------------------ #


def test_inverted_axis_limits(machine):
    machine["axes"][0]["position_max"] = -1.0
    assert "E_LIMITS" in _codes(machine)


def test_endstop_outside_the_limits(machine):
    machine["axes"][0]["position_endstop"] = 999.0
    assert "E_LIMITS" in _codes(machine)


def test_temp_and_rpm_ranges(machine):
    machine["tools"][0]["max_temp"] = 0.0
    machine["tools"].append(
        {"id": "spindle_digital", "type": "spindle_digital", "min_rpm": 24000, "max_rpm": 5000}
    )
    assert {"E_TEMP_RANGE", "E_RPM_RANGE"} <= _codes(machine)


# -- heaters ----------------------------------------------------------- #


def test_heater_id_must_carry_the_prefix(machine):
    machine["tools"][0]["id"] = "bed_heater"
    assert "E_HEATER_ID_PREFIX" in _codes(machine)


def test_two_heaters_cannot_share_one_sensor(machine):
    machine["tools"].append(
        {
            "id": "heater_extruder",
            "type": "extruder",
            "sensor": "bed",
            "heater_pin": "PB8",
        }
    )
    assert "E_SENSOR_SHARED" in _codes(machine)


# -- spindles ------------------------------------------------------------ #


def _with_vfd(machine, **spindle_overrides):
    machine = copy.deepcopy(machine)
    machine["mcus"].append({"id": "vfd0", "connection": "vfd_rs485"})
    spindle = {
        "id": "spindle_digital",
        "type": "spindle_digital",
        "min_rpm": 5000,
        "max_rpm": 24000,
        "run_pin": "vfd0:run-forward",
        "speed_pin": "vfd0:rpm-in",
        "at_speed_pin": "vfd0:at-speed",
        "is_connected_pin": "vfd0:is-connected",
    }
    spindle.update(spindle_overrides)
    machine["tools"].append(spindle)
    return machine


def test_a_complete_spindle_reports_nothing(machine):
    assert validate_machine(_with_vfd(machine)) == []


def test_spindle_without_a_run_pin_is_rejected(machine):
    complete = _with_vfd(machine)
    del complete["tools"][-1]["run_pin"]
    assert "E_SPINDLE_NO_RUN_PIN" in _codes(complete)


def test_spindle_without_a_speed_pin_is_rejected_unless_fixed_speed(machine):
    no_speed = _with_vfd(machine)
    del no_speed["tools"][-1]["speed_pin"]
    assert "E_SPINDLE_NO_SPEED_PIN" in _codes(no_speed)

    fixed_speed = _with_vfd(machine, min_rpm=12000, max_rpm=12000)
    del fixed_speed["tools"][-1]["speed_pin"]
    assert "E_SPINDLE_NO_SPEED_PIN" not in _codes(fixed_speed)


def test_spindle_with_no_feedback_warns_but_does_not_block(machine):
    complete = _with_vfd(machine)
    del complete["tools"][-1]["at_speed_pin"]
    diagnostics = validate_machine(complete)
    assert any(d.code == "W_NO_SPINDLE_FEEDBACK" for d in diagnostics)
    assert not MachineValidator.has_errors(diagnostics)


def test_spindle_pins_share_the_generic_mcu_and_conflict_checks(machine):
    unknown_mcu = _with_vfd(machine)
    unknown_mcu["tools"][-1]["run_pin"] = "ghost:run-forward"
    assert "E_UNKNOWN_MCU" in _codes(unknown_mcu)

    conflicting = _with_vfd(machine)
    conflicting["tools"][-1]["speed_pin"] = "vfd0:run-forward"  # same as run_pin
    assert "E_PIN_CONFLICT" in _codes(conflicting)


def test_a_spindle_on_a_serial_link_without_health_pins_warns(machine):
    no_health = _with_vfd(machine)
    del no_health["tools"][-1]["is_connected_pin"]
    diagnostics = validate_machine(no_health)
    assert any(d.code == "W_NO_SPINDLE_HEALTH" for d in diagnostics)


def test_two_spindles_cannot_share_one_spindle_number(machine):
    two_spindles = _with_vfd(machine)
    two_spindles["mcus"].append({"id": "vfd1", "connection": "vfd_rs485"})
    two_spindles["tools"].append(
        {
            "id": "spindle_digital_test",
            "type": "spindle_digital",
            "run_pin": "vfd1:run-forward",
            "speed_pin": "vfd1:rpm-in",
        }
    )
    assert "E_MULTIPLE_SPINDLES" in _codes(two_spindles)


def test_two_spindles_with_distinct_numbers_do_not_conflict(machine):
    two_spindles = _with_vfd(machine)
    two_spindles["mcus"].append({"id": "vfd1", "connection": "vfd_rs485"})
    two_spindles["tools"].append(
        {
            "id": "spindle_digital_test",
            "type": "spindle_digital",
            "spindle_number": 1,
            "run_pin": "vfd1:run-forward",
            "speed_pin": "vfd1:rpm-in",
        }
    )
    assert "E_MULTIPLE_SPINDLES" not in _codes(two_spindles)


# -- against the real machines in the repo ----------------------------- #


def test_the_shipped_example_machine_is_compilable():
    """Only the known, generator-created fan/heater pin sharing."""
    path = REPO_ROOT / "machine_config" / "machines" / "example" / "configs" / "hardware.json"
    if not path.exists():
        pytest.skip("example machine not generated in this checkout")

    diagnostics = validate_machine(json.loads(path.read_text(encoding="utf-8")))
    assert not MachineValidator.has_errors(diagnostics), [str(d) for d in diagnostics]
    assert {d.code for d in diagnostics} <= {"W_FAN_SHARES_HEATER_PIN"}


def _generated(profile: Path) -> dict[str, object]:
    from machineconfig_parser import MachineConfigParser
    from services.machineconfig.hardware_json_generator import build_hardware_json

    graph = MachineConfigParser().parse(profile)
    return json.loads(json.dumps(build_hardware_json(graph, profile.stem)))


def _profiles() -> list[Path]:
    return sorted((REPO_ROOT / "machine_config" / "profiles").glob("*.cfg"))


@pytest.mark.parametrize("profile", _profiles(), ids=lambda p: p.name)
def test_profiles_with_an_mcu_pass_the_gate(profile: Path):
    """Every profile that declares a board must compile end to end."""
    payload = _generated(profile)
    if not payload.get("mcus"):
        pytest.skip(f"{profile.name} declares no [mcu] — covered by the test below")

    blocking = [str(d) for d in validate_machine(payload) if d.is_error]
    assert not blocking, f"{profile.name} does not compile:\n  " + "\n  ".join(blocking)


def test_a_profile_without_an_mcu_is_rejected():
    """No board means nowhere to route pins — the gate must say so.

    ``motion_only_no_mcu.cfg`` ships without an ``[mcu]`` section (a
    dedicated fixture — the profile it used to piggyback off of,
    ``printer.cfg``, is now someone's real hardware profile and always
    declares a board). It is a valid Klipper-ish profile and valid
    hardware.json, but not a compilable machine, and the failure has
    to name that rather than emitting HAL full of dangling signals.
    """
    without_mcu = [p for p in _profiles() if not _generated(p).get("mcus")]
    assert without_mcu, "expected at least one MCU-less profile in the repo"

    for profile in without_mcu:
        codes = {d.code for d in validate_machine(_generated(profile))}
        assert "E_NO_MCU" in codes, profile.name
