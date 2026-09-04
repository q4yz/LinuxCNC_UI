"""Tests for ``HalMapper``.

Pins the Visual HAL editor's DTO -> resource translation contract:

* HAL type inference maps Python ``bool`` -> ``bit`` (bool must be
  checked before ``int`` since it is an int subclass), ``float`` ->
  ``float``, ``int`` -> ``s32``; unknown values degrade to ``float``
  instead of raising,
* pin mapping flattens ``<component>.<pin>`` into ``id`` /
  ``full_name`` and preserves direction / value / description,
* signal mapping derives the signal's type token from the source
  pin (or first target), and
* ``to_layout`` splits the pin set into the IN / OUT palettes.
"""

from __future__ import annotations

from dtos.pins.HalPin import HalDirection
from dtos.pins.MachineHalPin import MachineHalPin
from dtos.pins.MachineSignal import MachineHalSignal
from mappers.hal_mapper import HalMapper
from models.hal import HalLayoutResponse


def _pin(value, direction=HalDirection.IN, pin="probe", comp="mockcomp", doc="test pin"):
    return MachineHalPin(
        value=value,
        pin=pin,
        component_name=comp,
        description=doc,
        direction=direction,
    )


class TestInferHalType:
    def test_bool_maps_to_bit(self):
        # bool is an int subclass — the naive isinstance chain
        # would classify True as s32. This pins the ordering fix.
        assert HalMapper.infer_hal_type(True) == "bit"
        assert HalMapper.infer_hal_type(False) == "bit"

    def test_float_maps_to_float(self):
        assert HalMapper.infer_hal_type(0.0) == "float"
        assert HalMapper.infer_hal_type(-12.5) == "float"

    def test_int_maps_to_s32(self):
        assert HalMapper.infer_hal_type(0) == "s32"
        assert HalMapper.infer_hal_type(42) == "s32"

    def test_unknown_falls_back_to_float(self):
        assert HalMapper.infer_hal_type(None) == "float"
        assert HalMapper.infer_hal_type("weird") == "float"


class TestToPinResource:
    def test_flattens_full_name_and_id(self):
        resource = HalMapper.to_pin_resource(_pin(True, HalDirection.OUT, pin="spindle-on", comp="motion"))
        assert resource.full_name == "motion.spindle-on"
        assert resource.id == "motion.spindle-on"
        assert resource.component_name == "motion"
        assert resource.pin_name == "spindle-on"

    def test_preserves_direction_type_value_doc(self):
        resource = HalMapper.to_pin_resource(_pin(1200.0, HalDirection.OUT, doc="Spindle speed"))
        assert resource.direction == "out"
        assert resource.type == "float"
        assert resource.value == 1200.0
        assert resource.description == "Spindle speed"

    def test_in_direction_serialised_as_in(self):
        resource = HalMapper.to_pin_resource(_pin(False, HalDirection.IN))
        assert resource.direction == "in"


class TestToSignalResource:
    def test_type_taken_from_source_pin(self):
        source = _pin(1200.0, HalDirection.OUT, pin="speed-out")
        target = _pin(0.0, HalDirection.IN, pin="speed-fb")
        signal = MachineHalSignal(name="speed-sig", source=source, targets=(target,))
        resource = HalMapper.to_signal_resource(signal)

        assert resource.name == "speed-sig"
        assert resource.type == "float"
        assert resource.source is not None
        assert resource.source.full_name == "mockcomp.speed-out"
        assert [t.full_name for t in resource.targets] == ["mockcomp.speed-fb"]

    def test_type_falls_back_to_first_target_without_source(self):
        target = _pin(False, HalDirection.IN, pin="at-speed")
        resource = HalMapper.to_signal_resource(
            MachineHalSignal(name="orphan", source=None, targets=(target,))
        )
        assert resource.source is None
        assert resource.type == "bit"

    def test_empty_signal_defaults_to_bit(self):
        resource = HalMapper.to_signal_resource(MachineHalSignal(name="empty"))
        assert resource.type == "bit"
        assert resource.targets == []


class TestToLayout:
    def test_splits_pins_into_in_and_out_palettes(self):
        pins = [
            _pin(True, HalDirection.OUT, pin="writer"),
            _pin(False, HalDirection.IN, pin="reader-a"),
            _pin(1.0, HalDirection.IN, pin="reader-b"),
        ]
        layout = HalMapper.to_layout(pins, [])

        assert isinstance(layout, HalLayoutResponse)
        assert [p.pin_name for p in layout.in_pins] == ["reader-a", "reader-b"]
        assert [p.pin_name for p in layout.out_pins] == ["writer"]

    def test_signals_mapped_in_order(self):
        signal = MachineHalSignal(name="sig-1")
        layout = HalMapper.to_layout([], [signal])
        assert [s.name for s in layout.signals] == ["sig-1"]
