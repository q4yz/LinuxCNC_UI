"""Axis velocity / acceleration limits: hardware.json -> AxisStateResponse.

The frontend sizes its speed sliders from these, so an unknown limit
must stay ``None`` — never a guessed default.
"""
from __future__ import annotations

from core.field_masking import ResponseTier
from mappers.axis.AxisMapper import AxisMapper


def _axis(**extra):
    return {"id": "x", "joint_numbers": [0], "position_min": 0.0, "position_max": 900.0, **extra}


def test_limits_are_read_from_hardware_json():
    dto = AxisMapper.from_dict_to_dto(_axis(max_velocity=70.0, max_acceleration=400.0))
    assert (dto.max_velocity, dto.max_acceleration) == (70.0, 400.0)


def test_missing_zero_or_garbage_limits_stay_unknown():
    for raw in (None, 0, 0.0, -5, "fast"):
        dto = AxisMapper.from_dict_to_dto(_axis(max_velocity=raw, max_acceleration=raw))
        assert dto.max_velocity is None and dto.max_acceleration is None, raw
    assert AxisMapper.from_dict_to_dto(_axis()).max_velocity is None


def test_limits_are_static_tier_only():
    dto = AxisMapper.from_dict_to_dto(_axis(max_velocity=70.0, max_acceleration=400.0))
    static = AxisMapper.to_response(dto, ResponseTier.STATIC)
    assert (static.max_velocity, static.max_acceleration) == (70.0, 400.0)

    # The base tier masks static fields to None — this used to fail
    # pydantic validation (required fields) and 500 ``?mode=base``.
    base = AxisMapper.to_response(dto, ResponseTier.BASE)
    assert base.max_velocity is None and base.min_limit is None and base.joint_numbers is None
