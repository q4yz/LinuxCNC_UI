"""Skew correction: Klipper's factor from the calibration print's
diagonals (``SET_SKEW XY=AC,BD,AD``); a joint gets x - y * factor."""
from __future__ import annotations

import math


def skew_factor(ac: float, bd: float, ad: float) -> float:
    """``tan`` of the XY skew from the diagonals ``ac``, ``bd`` and the side
    ``ad`` of Klipper's skew calibration print (its calc_skew_factor)."""
    if min(ac, bd, ad) <= 0:
        raise ValueError("lengths must be above 0")
    side_sq = 2 * ac * ac + 2 * bd * bd - 4 * ad * ad
    if side_sq <= 0:
        raise ValueError("these lengths are no parallelogram")
    side = math.sqrt(side_sq) / 2
    cos_angle = (ac * ac - side * side - ad * ad) / (2 * side * ad)
    if not -1 <= cos_angle <= 1:
        raise ValueError("these lengths are no parallelogram")
    return math.tan(math.pi / 2 - math.acos(cos_angle))


__all__ = ["skew_factor"]
