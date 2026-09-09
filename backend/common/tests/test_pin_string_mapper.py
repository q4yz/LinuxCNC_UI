"""The pin-string grammar (`.agent/component/README.md` § 1).

Every pin value in hardware.json is `[modifiers][<mcu_id>:]<pin_id>`.
Getting this wrong routes a signal to the wrong board or silently drops
an inversion, so the parse is pinned here rather than trusted.
"""

import pytest

from mappers.machineconfig import PinStringMapper
from models.machineconfig.pin_models import DEFAULT_MCU_ID, CapabilityClass

parse = PinStringMapper.from_string


def test_bare_pin_belongs_to_the_default_mcu():
    pin = parse("PE3")
    assert (pin.mcu_id, pin.pin_id) == (DEFAULT_MCU_ID, "PE3")
    assert not (pin.invert or pin.pullup or pin.pulldown)


def test_modifiers_are_flags_not_part_of_the_pin_id():
    assert parse("!PF14") == parse("!PF14")
    inverted = parse("!PF14")
    assert inverted.pin_id == "PF14" and inverted.invert

    pulled_up = parse("^PC0")
    assert pulled_up.pin_id == "PC0" and pulled_up.pullup

    pulled_down = parse("~PC1")
    assert pulled_down.pin_id == "PC1" and pulled_down.pulldown


def test_modifiers_combine():
    pin = parse("^!PC0")
    assert (pin.pin_id, pin.pullup, pin.invert) == ("PC0", True, True)


def test_explicit_mcu_prefix():
    pin = parse("par0:02")
    assert (pin.mcu_id, pin.pin_id) == ("par0", "02")


def test_modifier_may_sit_either_side_of_the_prefix():
    """Hand-written configs use both spellings; accept each."""
    before = parse("!par0:02")
    after = parse("par0:!02")
    assert before.mcu_id == after.mcu_id == "par0"
    assert before.pin_id == after.pin_id == "02"
    assert before.invert and after.invert


def test_only_the_first_colon_splits():
    """An EtherCAT pin id is itself dotted/colonned — don't over-split."""
    pin = parse("ec0:din1:din-3")
    assert (pin.mcu_id, pin.pin_id) == ("ec0", "din1:din-3")


def test_qualified_identity_is_used_for_conflict_checks():
    assert parse("par0:02").qualified == "par0:02"
    # Same physical pin, different spellings of the modifier set.
    assert parse("!par0:02").qualified == parse("par0:02").qualified


@pytest.mark.parametrize("bad", ["", "   ", ":", ":PA1", "!", "par0:", "par0:!"])
def test_malformed_strings_raise(bad):
    with pytest.raises(ValueError):
        parse(bad)


def test_capability_class_per_connection():
    assert CapabilityClass.for_connection("parallelport") is CapabilityClass.STEP_DIR
    assert CapabilityClass.for_connection("remora-spi") is CapabilityClass.POSITION
    assert CapabilityClass.for_connection("remora-eth") is CapabilityClass.POSITION
    # A VFD is a controller — an MCU — but a peripheral one: it may
    # carry a spindle, never a joint. "rs485" is the pre-rename alias.
    assert CapabilityClass.for_connection("vfd_rs485") is CapabilityClass.IO_ONLY
    assert CapabilityClass.for_connection("rs485") is CapabilityClass.IO_ONLY
    # Unknown transports are reported, never guessed.
    assert CapabilityClass.for_connection("something-new") is None
    assert CapabilityClass.for_connection(None) is None
