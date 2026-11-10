"""Probing a list of X, Y points over MDI — Z tilt (``ZTiltService``) and
the bed mesh (``BedMeshProbeService``).

Per point: ``G53 G1 X Y`` at the travel speed, a probe move down to
machine ``Z<bottom>`` at the probe speed, the height from ``stat.probed_position`` (machine
coordinates), ``G53 G0 Z<safe>`` back up. LinuxCNC takes ``G53`` with
``G0``/``G1`` only ("Must use g0 or g1 with g53"), so the probe move is
relative — ``G91 G38.2 Z-<safe - bottom>`` from machine ``Z<safe>`` —
and independent of the work offsets. Each line waits until it is
finished (``MacroExecutionService._wait_until_idle``).
"""
from __future__ import annotations

import math
from typing import Any, Callable, List, Optional, Sequence

from hardware import dispatch_mdi
from services.MacroExecutionService import MacroExecutionService


#: A probe move stops this far above the lowest Z (the soft limit):
#: LinuxCNC refuses a probe target on or past it ("Probe move would
#: exceed Z's negative limit"), and the 4-decimal distance can round
#: past an exact one.
LIMIT_MARGIN_MM = 0.01


def probe_distance(from_z: float, bottom: float) -> float:
    """The relative ``G38.2`` distance from machine ``from_z`` down to
    :data:`LIMIT_MARGIN_MM` above ``bottom``, rounded down (never past it)."""
    return max(0.0, math.floor((from_z - bottom - LIMIT_MARGIN_MM) * 10_000) / 10_000)


class ProbeError(RuntimeError):
    """Why probing stopped."""


def mdi(stat: Any, line: str) -> None:
    try:
        serial = dispatch_mdi(line)
    except Exception as exc:  # noqa: BLE001
        raise ProbeError(f"{line!r}: LinuxCNC refused it ({exc}).") from exc
    reason = MacroExecutionService._wait_until_idle(stat, serial)
    if reason is not None:
        raise ProbeError(f"{line!r}: {reason}")


def probe_points(
    stat: Any,
    points: Sequence[tuple[float, float]],
    safe_z: float,
    travel_mm_s: float,
    probe_mm_s: float,
    bottom: float,
    progress: Optional[Callable[[int, float], None]] = None,
) -> List[float]:
    """The probed height at each point, in order."""
    if safe_z <= bottom:
        raise ProbeError(f"the travel height Z{safe_z:g} is not above the probe's lowest Z{bottom:g}.")
    mdi(stat, "G90")
    mdi(stat, f"G53 G0 Z{safe_z:.4f}")
    heights: List[float] = []
    for k, (x, y) in enumerate(points):
        mdi(stat, f"G53 G1 X{x:.4f} Y{y:.4f} F{travel_mm_s * 60.0:.1f}")
        mdi(stat, "G91")
        try:
            mdi(stat, f"G38.2 Z-{probe_distance(safe_z, bottom):.4f} F{probe_mm_s * 60.0:.1f}")
        finally:
            mdi(stat, "G90")
        stat.poll()
        if not getattr(stat, "probe_tripped", False):
            raise ProbeError(f"the probe did not trigger at X{x:g} Y{y:g} above Z{bottom:g}.")
        heights.append(float(stat.probed_position[2]))
        mdi(stat, f"G53 G0 Z{safe_z:.4f}")
        if progress is not None:
            progress(k, heights[-1])
    return heights


__all__ = ["ProbeError", "mdi", "probe_points"]
