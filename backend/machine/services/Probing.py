"""Probing a list of X, Y points over MDI — Z tilt (``ZTiltService``) and
the bed mesh (``BedMeshProbeService``).

The points are where the *probe* touches the bed: the nozzle goes to
``X - x_offset, Y - y_offset`` (``[probe]``, Klipper's meaning) and a
height is the nozzle's Z at the trigger minus ``z_offset`` — the bed
under the probe in nozzle Z.

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
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from hardware import dispatch_mdi
from services.MacroExecutionService import MacroExecutionService


#: A probe move stops this far above the lowest Z (the soft limit):
#: LinuxCNC refuses a probe target on or past it ("Probe move would
#: exceed Z's negative limit"), and the 4-decimal distance can round
#: past an exact one.
LIMIT_MARGIN_MM = 0.01

#: The probe's own signal, before the gate that passes it to
#: ``motion.probe-input`` only during G38 moves (``ProbeHalMapper``).
PROBE_SIGNAL = "probe-in"
#: How long a probe may take to report released after a move (s).
RELEASE_WAIT_S = 0.3


def probe_triggered() -> Optional[bool]:
    """The probe's own signal now, or ``None`` when it cannot be read."""
    from hardware.Connection import read_hal_pin

    value = read_hal_pin(PROBE_SIGNAL)
    return None if value is None else bool(value)


def wait_released(timeout: Optional[float] = None) -> Optional[bool]:
    """``True`` once the probe reports released, ``False`` if it is still
    triggered after ``timeout``, ``None`` when its signal cannot be read.

    LinuxCNC refuses a G38.2 that starts with ``motion.probe-input``
    already tripped, but the probe reaches that pin only *during* a probe
    move (the gate), so that check never fires: a probe still triggered —
    one whose release point lies above the retract (capacitive and
    inductive probes can have 1-2 mm of hysteresis) — would "trip" the
    moment the next probe move starts and report the start height as the
    bed. Checking the probe's own signal before each probe move brings
    that check back.
    """
    deadline = time.monotonic() + (RELEASE_WAIT_S if timeout is None else timeout)
    while True:
        state = probe_triggered()
        if state is None:
            return None
        if not state:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


def probe_distance(from_z: float, bottom: float) -> float:
    """The relative ``G38.2`` distance from machine ``from_z`` down to
    :data:`LIMIT_MARGIN_MM` above ``bottom``, rounded down (never past it)."""
    return max(0.0, math.floor((from_z - bottom - LIMIT_MARGIN_MM) * 10_000) / 10_000)


@dataclass(frozen=True)
class ProbeOffsets:
    """``[probe] x_offset / y_offset / z_offset`` (mm): the probe relative
    to the nozzle; the nozzle's height above the bed at the trigger."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ProbeOffsets":
        probe: Dict[str, Any] = payload.get("probe") if isinstance(payload.get("probe"), dict) else {}
        return cls(*(float(probe.get(k) or 0.0) for k in ("x_offset", "y_offset", "z_offset")))


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
    offsets: ProbeOffsets = ProbeOffsets(),
) -> List[float]:
    """The probed height at each (probe) point, in order."""
    if safe_z <= bottom:
        raise ProbeError(f"the travel height Z{safe_z:g} is not above the probe's lowest Z{bottom:g}.")
    mdi(stat, "G90")
    mdi(stat, f"G53 G0 Z{safe_z:.4f}")
    heights: List[float] = []
    for k, (x, y) in enumerate(points):
        mdi(stat, f"G53 G1 X{x - offsets.x:.4f} Y{y - offsets.y:.4f} F{travel_mm_s * 60.0:.1f}")
        if wait_released() is False:
            raise ProbeError(
                f"the probe is still triggered at X{x:g} Y{y:g} Z{safe_z:g}, before probing — raise the travel "
                "height (horizontal_move_z) above its release point, or check the probe."
            )
        mdi(stat, "G91")
        try:
            mdi(stat, f"G38.2 Z-{probe_distance(safe_z, bottom):.4f} F{probe_mm_s * 60.0:.1f}")
        finally:
            mdi(stat, "G90")
        stat.poll()
        if not getattr(stat, "probe_tripped", False):
            raise ProbeError(f"the probe did not trigger at X{x:g} Y{y:g} above Z{bottom:g}.")
        heights.append(float(stat.probed_position[2]) - offsets.z)
        mdi(stat, f"G53 G0 Z{safe_z:.4f}")
        if progress is not None:
            progress(k, heights[-1])
    return heights


__all__ = [
    "LIMIT_MARGIN_MM", "PROBE_SIGNAL", "ProbeError", "ProbeOffsets", "mdi", "probe_distance", "probe_points",
    "probe_triggered", "wait_released",
]
