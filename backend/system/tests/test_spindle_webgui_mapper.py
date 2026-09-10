"""SpindleWebguiMapper — `webgui_connections.hal` bindings for one spindle.

Pin names verified against the real runtime consumer,
`common/mappers/tools/SpindleDigitalMapper.py::from_dict_to_SpindleDigitalPins`
— `suffix = tool_id.replace("spindle_digital", "")`, `TargetRpm`
capitalised exactly that way, everything else lower-hyphenated.
"""

from __future__ import annotations

from services.halcompiler.components.SpindleWebguiMapper import SpindleWebguiMapper

FULL_SPINDLE = {
    "id": "spindle_digital",
    "run_pin": "vfd0:run-forward",
    "reverse_pin": "vfd0:run-reverse",
    "speed_pin": "vfd0:rpm-in",
    "speed_fb_pin": "vfd0:rpm-out",
    "at_speed_pin": "vfd0:at-speed",
    "fault_pin": "vfd0:fault",
    "is_connected_pin": "vfd0:is-connected",
    "error_count_pin": "vfd0:error-count",
}


def test_commanded_speed_is_always_bound():
    lines = SpindleWebguiMapper.to_lines({"id": "spindle_digital", "run_pin": "vfd0:run-forward"})
    assert "net spindle-speed-cmd => webgui.TargetRpm" in lines


def test_full_spindle_binds_every_readout():
    lines = SpindleWebguiMapper.to_lines(FULL_SPINDLE)
    assert "net spindle-speed-fb => webgui.rpm-out" in lines
    assert "net spindle-at-speed => webgui.spindle-at-speed" in lines
    assert "net spindle-forward => webgui.spindle-forward" in lines
    assert "net spindle-reverse => webgui.spindle-reverse" in lines
    assert "net spindle_digital-is-connected => webgui.is-connected" in lines
    assert "net spindle_digital-error-count => webgui.error-count" in lines
    # The runtime's "last error" is this compiler's "fault" signal.
    assert "net spindle_digital-fault => webgui.last-error" in lines


def test_second_spindle_gets_a_suffixed_pin_never_colliding_with_the_first():
    lines = SpindleWebguiMapper.to_lines(dict(FULL_SPINDLE, id="spindle_digital_test"))
    assert "net spindle-speed-cmd => webgui.TargetRpm_test" in lines
    assert "net spindle-at-speed => webgui.spindle-at-speed_test" in lines
    assert "net spindle_digital_test-is-connected => webgui.is-connected_test" in lines
    # No bare (unsuffixed) pin name leaked through.
    assert not any(line.endswith("webgui.TargetRpm") for line in lines)


def test_at_speed_only_bound_when_the_signal_actually_exists():
    """No `at_speed_pin` and no `speed_fb_pin` -> `DigitalSpindleHalMapper`
    forces `at-speed` true via `setp`, no `spindle-at-speed` signal at
    all — binding it here would reference a signal nothing wrote."""
    minimal = {"id": "spindle_digital", "run_pin": "vfd0:run-forward"}
    lines = SpindleWebguiMapper.to_lines(minimal)
    assert not any("spindle-at-speed" in line for line in lines)


def test_optional_pins_are_independently_optional():
    minimal = {"id": "spindle_digital", "run_pin": "vfd0:run-forward"}
    lines = SpindleWebguiMapper.to_lines(minimal)
    assert not any("reverse" in line for line in lines)
    assert not any("is-connected" in line for line in lines)
    assert not any("error-count" in line for line in lines)
    assert not any("last-error" in line for line in lines)
    assert not any("rpm-out" in line for line in lines)
