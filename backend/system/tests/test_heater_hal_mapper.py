"""HeaterHalMapper — thermal half of `.agent/component/heater.md` § 3
(and `exturder.md`'s "identical, not repeated" thermal half).

Facts asserted here are quoted from `machine_config/example/ender3/
3Dprinter.hal`'s real bed and extruder-0 `PIDcontroller` sections, not
invented.
"""

from __future__ import annotations

from models.machineconfig.hal_fragment_models import PinRole
from services.halcompiler.components.HeaterHalMapper import HeaterHalMapper

BED = {"id": "heater_bed", "type": "heated_bed", "sensor": "bed", "heater_pin": "PB7", "control": "pid"}
BED_SENSOR = {"id": "bed", "pin": "PA0"}


def test_pid_loop_matches_the_reference_machine_shape():
    fragment = HeaterHalMapper.to_fragment(BED, BED_SENSOR, None)

    assert "loadrt PIDcontroller names=PID-heater_bed" in fragment.loadrt
    assert "net remora-status => PID-heater_bed.auto" in fragment.nets
    assert "net heater_bed-SP => PID-heater_bed.SP" in fragment.nets
    assert "net bed-PV => PID-heater_bed.PV" in fragment.nets
    assert "net heater_bed-heater-SP <= PID-heater_bed.CV" in fragment.nets


def test_pid_setp_block_references_the_ini_section_by_id_suffix():
    fragment = HeaterHalMapper.to_fragment(BED, BED_SENSOR, None)
    assert "setp PID-heater_bed.pOnM [BED]PID_PONM" in fragment.setp
    assert "setp PID-heater_bed.direction [BED]PID_DIR" in fragment.setp
    assert "setp PID-heater_bed.SPmax [BED]PID_SPMAX" in fragment.setp
    assert "setp PID-heater_bed.CVmax [BED]PID_CVMAX" in fragment.setp


def test_pid_compute_is_addf_on_servo_thread():
    fragment = HeaterHalMapper.to_fragment(BED, BED_SENSOR, None)
    addf = next(a for a in fragment.addf if a.func == "PID-heater_bed.compute")
    assert addf.thread == "servo-thread"


def test_extruder_ini_section_derives_from_its_own_id_suffix():
    extruder = dict(BED, id="heater_extruder", sensor="extruder")
    fragment = HeaterHalMapper.to_fragment(extruder, {"id": "extruder", "pin": "PA1"}, None)
    assert "setp PID-heater_extruder.KP [EXTRUDER]PID_KP" in fragment.setp


def test_watermark_loop_uses_a_comp_block_not_pid():
    heater = dict(BED, control="watermark")
    fragment = HeaterHalMapper.to_fragment(heater, BED_SENSOR, None)

    assert "loadrt comp names=comp-heater_bed" in fragment.loadrt
    assert not any("PIDcontroller" in line for line in fragment.loadrt)
    assert "setp comp-heater_bed.hyst 2.0" in fragment.setp
    assert "net bed-PV => comp-heater_bed.in0" in fragment.nets
    assert "net heater_bed-SP => comp-heater_bed.in1" in fragment.nets


def test_watermark_loop_converts_the_comparator_bit_to_a_duty_float():
    """`comp.out` is a HAL bit; `<id>-heater-SP` is routed straight
    into `remora.SP.N`, a float duty-cycle channel — linking a bit pin
    to a float pin is a HAL load-time type error. `conv_bit_float`
    (the same idiom `fan.md`'s `kind: heater` gating already uses)
    plus a `scale` stage fixes it, landing "on" at `max_power` percent
    so it matches the PID branch's own `CVmax` convention."""
    heater = dict(BED, control="watermark")
    fragment = HeaterHalMapper.to_fragment(heater, BED_SENSOR, None)

    assert "loadrt conv_bit_float names=conv-heater_bed" in fragment.loadrt
    assert "loadrt scale names=duty-heater_bed" in fragment.loadrt
    assert "setp duty-heater_bed.gain 100.0" in fragment.setp
    assert "net heater_bed-heat-bit comp-heater_bed.out => conv-heater_bed.in" in fragment.nets
    assert "net heater_bed-heat-frac conv-heater_bed.out => duty-heater_bed.in" in fragment.nets
    assert "net heater_bed-heater-SP <= duty-heater_bed.out" in fragment.nets
    # The old direct bit->float link must be gone, not just supplemented.
    assert not any("comp-heater_bed.out" in n and "heater-SP" in n for n in fragment.nets)


def test_watermark_duty_ceiling_honours_max_power():
    heater = dict(BED, control="watermark", max_power=80.0)
    fragment = HeaterHalMapper.to_fragment(heater, BED_SENSOR, None)
    assert "setp duty-heater_bed.gain 80.0" in fragment.setp


def test_heater_pin_is_requested_as_analog_out():
    fragment = HeaterHalMapper.to_fragment(BED, BED_SENSOR, None)
    request = next(r for r in fragment.requests if r.signal == "heater_bed-heater-SP")
    assert request.role is PinRole.ANALOG_OUT
    assert request.pin.pin_id == "PB7"


def test_sensor_pin_is_requested_as_analog_in():
    fragment = HeaterHalMapper.to_fragment(BED, BED_SENSOR, None)
    request = next(r for r in fragment.requests if r.signal == "bed-PV")
    assert request.role is PinRole.ANALOG_IN
    assert request.pin.pin_id == "PA0"


def test_a_heater_without_a_sensor_still_compiles():
    """A tool can declare no sensor yet — the loop just runs open-loop."""
    fragment = HeaterHalMapper.to_fragment(BED, None, None)
    assert not any("-PV" in n for n in fragment.nets)
    assert not any(r.role is PinRole.ANALOG_IN for r in fragment.requests)
    # The setpoint/output wiring is unaffected.
    assert "net heater_bed-SP => PID-heater_bed.SP" in fragment.nets


def test_referenced_fan_is_a_plain_analog_out_passthrough():
    """Matches the reference machine: `ext0-cooling-SP => remora.SP.2`,
    no temperature gating — `fan.md`'s richer `kind: heater` behaviour
    needs schema fields `fans[]` doesn't carry yet."""
    heater = dict(BED, fan="fan_heater_bed")
    fan = {"id": "fan_heater_bed", "pin": "PB1"}
    fragment = HeaterHalMapper.to_fragment(heater, BED_SENSOR, fan)

    request = next(r for r in fragment.requests if r.signal == "fan_heater_bed-SP")
    assert request.role is PinRole.ANALOG_OUT
    assert request.pin.pin_id == "PB1"
    assert request.owner == "heater_bed"


def test_no_fan_reference_means_no_fan_request():
    fragment = HeaterHalMapper.to_fragment(BED, BED_SENSOR, None)
    assert not any(r.signal.endswith("-SP") and r.owner == "heater_bed" and "heater-SP" not in r.signal for r in fragment.requests)


def test_a_fan_referenced_but_not_resolved_is_skipped_not_crashed():
    """The assembler passes `None` when the referenced fan id isn't in
    `fans[]` — validated input wouldn't hit this, but the mapper must
    not blow up on it either."""
    heater = dict(BED, fan="ghost_fan")
    fragment = HeaterHalMapper.to_fragment(heater, BED_SENSOR, None)
    assert not any(r.signal == "ghost_fan-SP" for r in fragment.requests)
