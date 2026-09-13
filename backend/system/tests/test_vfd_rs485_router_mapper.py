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
    baud_rate) flow straight into the vfd.ini sidecar's [RS485]
    block, using vfdmod's real key names."""
    mcu = {
        "id": "vfd0",
        "connection": "vfd_rs485",
        "interface": "/dev/ttyUSB0",
        "node_id": 3,
        "baud_rate": 19200,
    }
    fragment = VfdRs485RouterMapper.base_fragment(mcu)
    ini = fragment.files["vfd_vfd0.ini"]
    assert "SerialDevice=/dev/ttyUSB0" in ini
    assert "SlaveAddress=3" in ini
    assert "BaudRate=19200" in ini


def test_ini_sidecar_reads_the_spindle_rpm_range_stitched_in_by_the_assembler():
    """MaxSpeedRPM/MinSpeedRPM come from the spindle tool, not the
    MCU record — the assembler stitches ``_spindle_min_rpm`` /
    ``_spindle_max_rpm`` onto the MCU dict before calling this
    (see ``HalAssembler._enrich_mcu_for_base``)."""
    mcu = {"id": "vfd0", "_spindle_min_rpm": 3000, "_spindle_max_rpm": 18000}
    fragment = VfdRs485RouterMapper.base_fragment(mcu)
    ini = fragment.files["vfd_vfd0.ini"]
    assert "MaxSpeedRPM=18000" in ini
    assert "MinSpeedRPM=3000" in ini


def test_ini_sidecar_falls_back_to_the_reference_machines_known_good_defaults():
    """No MCU/spindle fields at all — every value falls back to
    ``machine_config/example/PrintNC-WEBGUI/vfd.ini``'s own numbers."""
    fragment = VfdRs485RouterMapper.base_fragment({"id": "vfd0"})
    ini = fragment.files["vfd_vfd0.ini"]
    assert "MaxSpeedRPM=24000" in ini
    assert "MinSpeedRPM=5000" in ini
    assert "SlaveAddress=1" in ini
    assert "SerialDevice=/dev/ttyUSB0" in ini
    assert "BaudRate=19200" in ini
    assert "DataBits=8" in ini
    assert "Parity=N" in ini
    assert "StopBits=1" in ini


def test_ini_sidecar_carries_the_reference_register_map_verbatim():
    """The Modbus register map is drive-specific and not ingested
    from the profile yet — every value here must come straight from
    the reference machine, unedited."""
    fragment = VfdRs485RouterMapper.base_fragment({"id": "vfd0"})
    ini = fragment.files["vfd_vfd0.ini"]
    assert "[Control]" in ini
    assert "Address=0x2000" in ini
    assert "RunForwardValue=0x0012" in ini
    assert "StopValue=0x0001" in ini
    assert "[SpindleRpmIn]" in ini
    assert "[SpindleRpmOut]" in ini
    assert "[P00.00]" in ini
    assert "[P11.04]" in ini


def test_output_pins_route_with_an_arrow_into_vfdmod():
    fragment = VfdRs485RouterMapper.route([_request("vfd0:run-forward")])
    assert "net spindle-forward => vfdmod.control.run-forward" in fragment.nets


def test_input_pins_route_with_an_arrow_out_of_vfdmod():
    request = _request("vfd0:rpm-out", role=PinRole.SPINDLE_IN)
    fragment = VfdRs485RouterMapper.route([request])
    assert "net spindle-forward <= vfdmod.spindle.rpm-out" in fragment.nets


def test_rpm_in_routes_to_the_spindle_group_not_control():
    """Real bug: this used to map to `vfdmod.control.rpm-in`, which
    doesn't exist on a real vfdmod build ("Pin 'vfdmod.control.rpm-in'
    does not exist" at LinuxCNC startup) — verified against
    `machine_config/example/PrintNC-WEBGUI/webgui_connections.hal`'s
    own working wiring, the RPM command pin lives under
    `vfdmod.spindle.*` alongside `rpm-out`, not `vfdmod.control.*`
    with `run-forward`/`run-reverse`."""
    fragment = VfdRs485RouterMapper.route([_request("vfd0:rpm-in")])
    assert "net spindle-forward => vfdmod.spindle.rpm-in" in fragment.nets


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
    # ``;`` comments and duplicate-looking keys across sections
    # (vfdmod's own style) parse fine as long as the file is
    # well-formed INI — this is the check that would have caught the
    # earlier ``[common]``/``[rpmIn]`` shape actually being wrong
    # for what vfdmod expects, since it still parsed as valid INI.
    parser = configparser.ConfigParser(strict=False, inline_comment_prefixes=(";",))
    parser.read_string(fragment.files["vfd_vfd0.ini"])
    assert parser["Common"]["MaxSpeedRPM"] == "24000"
    assert parser["RS485"]["BaudRate"] == "19200"
