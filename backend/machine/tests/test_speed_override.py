"""Speed override read-back: ``stat.feedrate`` / ``stat.max_velocity``.

The UI's Speed Multiplier / Max Speed sliders are confirmed by this
read-back, so unknown values must stay ``None`` and a command must be
reflected in the next read.
"""
from __future__ import annotations

from types import SimpleNamespace

from core.field_masking import ResponseTier
from dtos.axis.SpeedOverrideDto import SpeedOverrideDTO
from mappers.axis.speed_override_mapper import SpeedOverrideMapper


def test_stat_values_map_through():
    dto = SpeedOverrideMapper.from_stat(SimpleNamespace(feedrate=1.25, max_velocity=70.0))
    assert (dto.feed_override, dto.max_velocity) == (1.25, 70.0)


def test_zero_feed_override_is_a_real_value_but_zero_speed_cap_is_not():
    dto = SpeedOverrideMapper.from_stat(SimpleNamespace(feedrate=0.0, max_velocity=0.0))
    assert dto.feed_override == 0.0  # feed hold — legal
    assert dto.max_velocity is None


def test_missing_or_garbage_stat_values_stay_unknown():
    assert SpeedOverrideMapper.from_stat(None) == SpeedOverrideDTO()
    dto = SpeedOverrideMapper.from_stat(SimpleNamespace(feedrate="x", max_velocity=float("nan")))
    assert dto.feed_override is None and dto.max_velocity is None
    dto = SpeedOverrideMapper.from_stat(SimpleNamespace(feedrate=-1.0))
    assert dto.feed_override is None and dto.max_velocity is None


def test_response_is_base_tier_only():
    dto = SpeedOverrideDTO(feed_override=1.0, max_velocity=70.0)
    base = SpeedOverrideMapper.to_response(dto, ResponseTier.BASE)
    assert (base.feed_override, base.max_velocity) == (1.0, 70.0)
    static = SpeedOverrideMapper.to_response(dto, ResponseTier.STATIC)
    assert static.feed_override is None and static.max_velocity is None


def test_mock_reflects_feedrate_and_maxvel_commands():
    """update_settings -> command.feedrate/maxvel -> stat read-back,
    the same loop real LinuxCNC closes."""
    from hardware.mock.LinuxCNCMock import linuxcnc as mock_linuxcnc

    cmd = mock_linuxcnc.command()
    stat = mock_linuxcnc.stat()
    cmd.feedrate(0.5)
    cmd.maxvel(25.0)
    dto = SpeedOverrideMapper.from_stat(stat)
    assert (dto.feed_override, dto.max_velocity) == (0.5, 25.0)
    # Restore the shared mock for other tests.
    cmd.feedrate(1.0)
    cmd.maxvel(100.0)
