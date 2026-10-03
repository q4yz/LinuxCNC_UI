import math
from typing import Any, Optional

from core.field_masking import ResponseTier, include_base
from dtos.axis.SpeedOverrideDto import SpeedOverrideDTO
from models.axis_model import SpeedOverrideResponse


def _finite(raw: Any, *, positive: bool) -> Optional[float]:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    if value < 0 or (positive and value == 0):
        return None
    return value


class SpeedOverrideMapper:
    """``linuxcnc.stat`` -> ``SpeedOverrideDTO`` -> ``SpeedOverrideResponse``."""

    @classmethod
    def from_stat(cls, stat: Any) -> SpeedOverrideDTO:
        if stat is None:
            return SpeedOverrideDTO()
        return SpeedOverrideDTO(
            # 0 % is a legal override (feed hold), so only negatives are out.
            feed_override=_finite(getattr(stat, "feedrate", None), positive=False),
            # A 0 speed cap is never a real setting — treat it as unknown.
            max_velocity=_finite(getattr(stat, "max_velocity", None), positive=True),
        )

    @classmethod
    def to_response(cls, dto: SpeedOverrideDTO, r: ResponseTier = ResponseTier.ALL) -> SpeedOverrideResponse:
        # Live values — only on the 1 Hz base tier (and ``all``).
        return SpeedOverrideResponse(
            feed_override=include_base(dto.feed_override, r),
            max_velocity=include_base(dto.max_velocity, r),
        )


__all__ = ["SpeedOverrideMapper"]
