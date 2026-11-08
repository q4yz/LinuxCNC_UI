"""Probing a list of X, Y points over MDI — Z tilt (``ZTiltService``) and
the bed mesh (``BedMeshProbeService``).

Per point: ``G53 G1 X Y`` at the travel speed, ``G53 G38.2 Z<bottom>``
at the probe speed, the height from ``stat.probed_position`` (machine
coordinates), ``G53 G0 Z<safe>`` back up. Each line waits until it is
finished (``MacroExecutionService._wait_until_idle``).
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence

from hardware import dispatch_mdi
from services.MacroExecutionService import MacroExecutionService


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
    mdi(stat, "G90")
    mdi(stat, f"G53 G0 Z{safe_z:.4f}")
    heights: List[float] = []
    for k, (x, y) in enumerate(points):
        mdi(stat, f"G53 G1 X{x:.4f} Y{y:.4f} F{travel_mm_s * 60.0:.1f}")
        mdi(stat, f"G53 G38.2 Z{bottom:.4f} F{probe_mm_s * 60.0:.1f}")
        stat.poll()
        if not getattr(stat, "probe_tripped", False):
            raise ProbeError(f"the probe did not trigger at X{x:g} Y{y:g} above Z{bottom:g}.")
        heights.append(float(stat.probed_position[2]))
        mdi(stat, f"G53 G0 Z{safe_z:.4f}")
        if progress is not None:
            progress(k, heights[-1])
    return heights


__all__ = ["ProbeError", "mdi", "probe_points"]
