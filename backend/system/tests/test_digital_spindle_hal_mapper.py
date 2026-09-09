"""DigitalSpindleHalMapper — `.agent/component/digital_spindle.md` § 3.

Transport-independent: every test here builds a plain spindle dict
(the shape `hardware_json_generator._tool_payload_from_spindle_digital`
emits) and never mentions an MCU connection type — that split is the
whole point of the component/router boundary.
"""

from __future__ import annotations

from models.machineconfig.hal_fragment_models import PinRole
from services.halcompiler.components.DigitalSpindleHalMapper import DigitalSpindleHalMapper

FULL_SPINDLE = {
    "id": "spindle_digital",
    "type": "spindle_digital",
    "min_rpm": 5000.0,
    "max_rpm": 24000.0,
    "spindle_number": 0,
    "rpm_scale": 1.0,
    "run_pin": "vfd0:run-forward",
    "reverse_pin": "vfd0:run-reverse",
    "speed_pin": "vfd0:rpm-in",
    "speed_fb_pin": "vfd0:rpm-out",
    "at_speed_pin": "vfd0:at-speed",
    "fault_pin": "vfd0:fault",
    "is_connected_pin": "vfd0:is-connected",
    "error_count_pin": "vfd0:error-count",
}


def _signals(fragment):
    return {r.signal for r in fragment.requests}


def test_unscaled_speed_command_binds_directly_no_scale_block():
    fragment = DigitalSpindleHalMapper.to_fragment(FULL_SPINDLE)
    assert "net spindle-speed-cmd spindle.0.speed-out" in fragment.nets
    assert not any("scale-spindle_digital-cmd" in line for line in fragment.loadrt)

    request = next(r for r in fragment.requests if r.role is PinRole.SPINDLE_OUT and r.pin.pin_id == "rpm-in")
    assert request.signal == "spindle-speed-cmd"


def test_scaled_speed_command_gets_its_own_scale_block_and_signal():
    spindle = dict(FULL_SPINDLE, rpm_scale=2.5)
    fragment = DigitalSpindleHalMapper.to_fragment(spindle)

    assert "net spindle-speed-cmd spindle.0.speed-out => scale-spindle_digital-cmd.in" in fragment.nets
    assert "loadrt scale names=scale-spindle_digital-cmd" in fragment.loadrt
    assert "setp scale-spindle_digital-cmd.gain 2.5" in fragment.setp
    assert "net spindle_digital-speed-out scale-spindle_digital-cmd.out" in fragment.nets

    request = next(r for r in fragment.requests if r.pin.pin_id == "rpm-in")
    assert request.signal == "spindle_digital-speed-out"


def test_run_pin_always_requested_reverse_pin_only_when_declared():
    fragment = DigitalSpindleHalMapper.to_fragment(FULL_SPINDLE)
    assert "net spindle-forward spindle.0.forward" in fragment.nets
    assert "net spindle-reverse spindle.0.reverse" in fragment.nets
    assert {"spindle-forward", "spindle-reverse"} <= _signals(fragment)

    no_reverse = dict(FULL_SPINDLE)
    del no_reverse["reverse_pin"]
    fragment = DigitalSpindleHalMapper.to_fragment(no_reverse)
    assert not any("reverse" in n for n in fragment.nets)
    assert "spindle-reverse" not in _signals(fragment)


def test_at_speed_pin_present_wires_the_drives_own_bit():
    fragment = DigitalSpindleHalMapper.to_fragment(FULL_SPINDLE)
    assert "net spindle-at-speed => spindle.0.at-speed" in fragment.nets
    assert not any(line.startswith("loadrt near") for line in fragment.loadrt)


def test_speed_fb_only_derives_at_speed_with_a_near_component():
    spindle = dict(FULL_SPINDLE, min_rpm=5000.0)
    del spindle["at_speed_pin"]
    fragment = DigitalSpindleHalMapper.to_fragment(spindle)

    assert "loadrt near names=near-spindle_digital-at-speed" in fragment.loadrt
    assert "setp near-spindle_digital-at-speed.scale 1.02" in fragment.setp
    assert "setp near-spindle_digital-at-speed.difference 250.0" in fragment.setp
    assert "net spindle-speed-cmd => near-spindle_digital-at-speed.in1" in fragment.nets
    assert "net spindle-speed-fb => near-spindle_digital-at-speed.in2" in fragment.nets
    assert "net spindle-at-speed near-spindle_digital-at-speed.out => spindle.0.at-speed" in fragment.nets


def test_no_feedback_at_all_forces_at_speed_true():
    spindle = {"id": "spindle_digital", "run_pin": "vfd0:run-forward", "speed_pin": "vfd0:rpm-in"}
    fragment = DigitalSpindleHalMapper.to_fragment(spindle)
    assert "setp spindle.0.at-speed true" in fragment.setp
    assert not any("at-speed" in n for n in fragment.nets)
    assert not any(line.startswith("loadrt near") for line in fragment.loadrt)


def test_health_pins_get_requests_but_no_component_side_net():
    fragment = DigitalSpindleHalMapper.to_fragment(FULL_SPINDLE)
    signals = _signals(fragment)
    assert {"spindle_digital-fault", "spindle_digital-is-connected", "spindle_digital-error-count"} <= signals
    for signal in ("spindle_digital-fault", "spindle_digital-is-connected", "spindle_digital-error-count"):
        assert not any(signal in n for n in fragment.nets)


def test_health_pins_are_independently_optional():
    spindle = dict(FULL_SPINDLE)
    del spindle["fault_pin"]
    fragment = DigitalSpindleHalMapper.to_fragment(spindle)
    signals = _signals(fragment)
    assert "spindle_digital-fault" not in signals
    assert {"spindle_digital-is-connected", "spindle_digital-error-count"} <= signals


def test_spindle_number_selects_the_linuxcnc_spindle_index():
    spindle = dict(FULL_SPINDLE, id="spindle_digital_test", spindle_number=1)
    fragment = DigitalSpindleHalMapper.to_fragment(spindle)
    assert "net spindle-forward spindle.1.forward" in fragment.nets
    assert "net spindle-speed-cmd spindle.1.speed-out" in fragment.nets


def test_missing_spindle_number_defaults_to_zero():
    spindle = {"id": "spindle_digital", "run_pin": "vfd0:run-forward", "speed_pin": "vfd0:rpm-in"}
    fragment = DigitalSpindleHalMapper.to_fragment(spindle)
    assert "net spindle-forward spindle.0.forward" in fragment.nets
