"""VfdRs485RouterMapper — `.agent/component/mcu_vfd_rs485.md` § 3-4."""

from __future__ import annotations

import pytest

from mappers.machineconfig import PinStringMapper
from models.machineconfig.hal_fragment_models import PinRequest, PinRole
from services.halcompiler.mcus.VfdRs485RouterMapper import UnknownVfdPinError, VfdRs485RouterMapper


def _request(pin_string: str, owner: str = "spindle_digital", role: PinRole = PinRole.SPINDLE_OUT) -> PinRequest:
    return PinRequest(signal="spindle-forward", role=role, pin=PinStringMapper.from_string(pin_string), owner=owner)


def test_base_fragment_loads_vfdmod_with_a_wait_flag():
    fragment = VfdRs485RouterMapper.base_fragment({"id": "vfd0"})
    assert fragment.loadusr == ["loadusr -W vfdmod vfd_vfd0.ini"]
    assert fragment.addf == []  # class C: no realtime thread at all


def test_base_fragment_has_no_realtime_component():
    """A VFD link must never carry anything safety- or motion-critical."""
    fragment = VfdRs485RouterMapper.base_fragment({"id": "vfd0"})
    assert fragment.loadrt == []
    assert fragment.addf == []


def test_ini_sidecar_reads_the_ingested_serial_fields():
    """The MCU record's ingested fields (interface / node_id /
    baud_rate / parity) flow straight into the vfd.ini sidecar."""
    mcu = {
        "id": "vfd0",
        "connection": "vfd_rs485",
        "interface": "/dev/ttyUSB0",
        "node_id": 3,
        "baud_rate": 19200,
        "parity": "even",
    }
    fragment = VfdRs485RouterMapper.base_fragment(mcu)
    ini = fragment.files["vfd_vfd0.ini"]
    assert "port     = /dev/ttyUSB0" in ini
    assert "address  = 3" in ini
    assert "baud     = 19200" in ini
    assert "parity   = even" in ini


def test_ini_sidecar_falls_back_to_documented_defaults():
    fragment = VfdRs485RouterMapper.base_fragment({"id": "vfd0"})
    ini = fragment.files["vfd_vfd0.ini"]
    assert "address  = 1" in ini
    assert "baud     = 9600" in ini
    assert "parity   = none" in ini
    assert "databits = 8" in ini
    assert "stopbits = 1" in ini


def test_output_pins_route_with_an_arrow_into_vfdmod():
    fragment = VfdRs485RouterMapper.route([_request("vfd0:run-forward")])
    assert "net spindle-forward => vfdmod.control.run-forward" in fragment.nets


def test_input_pins_route_with_an_arrow_out_of_vfdmod():
    request = _request("vfd0:rpm-out", role=PinRole.SPINDLE_IN)
    fragment = VfdRs485RouterMapper.route([request])
    assert "net spindle-forward <= vfdmod.spindle.rpm-out" in fragment.nets


def test_health_pins_route_through_the_same_generic_table():
    for pin_id, hal_pin in (
        ("fault", "vfdmod.rs485.last-error"),
        ("is-connected", "vfdmod.rs485.is-connected"),
        ("error-count", "vfdmod.rs485.error-count"),
    ):
        request = _request(f"vfd0:{pin_id}", role=PinRole.SPINDLE_IN)
        fragment = VfdRs485RouterMapper.route([request])
        assert f"net spindle-forward <= {hal_pin}" in fragment.nets


def test_unknown_pin_id_raises_instead_of_emitting_bad_hal():
    with pytest.raises(UnknownVfdPinError, match="frobnicate"):
        VfdRs485RouterMapper.route([_request("vfd0:frobnicate")])


def test_inverted_output_gets_a_not_stage_before_the_pin():
    fragment = VfdRs485RouterMapper.route([_request("vfd0:!run-forward")])
    assert "loadrt not names=not-spindle_digital-spindle_out" in fragment.loadrt
    assert "net spindle-forward => not-spindle_digital-spindle_out.in" in fragment.nets
    assert "net spindle-forward-raw not-spindle_digital-spindle_out.out => vfdmod.control.run-forward" in fragment.nets


def test_inverted_input_gets_a_not_stage_after_the_pin():
    request = _request("vfd0:!at-speed", role=PinRole.SPINDLE_IN)
    fragment = VfdRs485RouterMapper.route([request])
    assert "loadrt not names=not-spindle_digital-spindle_in" in fragment.loadrt
    assert "net spindle-forward-raw vfdmod.spindle.at-speed => not-spindle_digital-spindle_in.in" in fragment.nets
    assert "net spindle-forward not-spindle_digital-spindle_in.out" in fragment.nets


def test_ini_sidecar_is_valid_ini_text():
    import configparser

    fragment = VfdRs485RouterMapper.base_fragment({"id": "vfd0"})
    parser = configparser.ConfigParser()
    parser.read_string(fragment.files["vfd_vfd0.ini"])
    # Register addresses stay empty until a `model` field selects a
    # drive-specific map (mcu_vfd_rs485.md § 3) — the section must
    # still parse so vfdmod can report the gap itself.
    assert parser["rpmIn"]["address"] == ""
    assert parser["common"]["baud"] == "9600"
