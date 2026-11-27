"""Probing a list of X, Y points over MDI — Z tilt (``ZTiltService``) and
the bed mesh (``BedMeshProbeService``).

The points are where the *probe* touches the bed: the nozzle goes to
``X - x_offset, Y - y_offset`` (``[probe]``, Klipper's meaning) and a
height is the nozzle's Z at the trigger minus ``z_offset`` — the bed
under the probe in nozzle Z.

Per point: ``G53 G1 X Y`` at the travel speed, :func:`probe_down`, ``G53 G0
Z<safe>`` back up.

:func:`probe_down` — every probing move (Z tilt, bed mesh, ``PROBE_ACCURACY``,
``PROBE_CALIBRATE``):

* **Two passes** (``[probe] second_speed`` / ``second_retract``, defaults
  :data:`DEFAULT_SECOND_SPEED` / :data:`DEFAULT_SECOND_RETRACT`): fast down to
  find the bed, back up ``second_retract`` (until the probe reports released),
  then slowly. LinuxCNC sees the probe once per servo period (1 ms): at 5 mm/s
  that is a 0.005 mm grid plus a few ms of jitter, at 1 mm/s a fifth of it.
* **The board's latch** (Remora "Probe Latch", the HAL signal ``probe-latch``):
  Z's step count at the trigger edge, exact to 25 us; used instead of
  ``stat.probed_position`` when it captured during the move and agrees within
  :data:`LATCH_SANITY_MM`. Without one, LinuxCNC's own latched position. LinuxCNC takes ``G53`` with
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
from services.program.MacroExecutionService import MacroExecutionService


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

#: Two-pass probing defaults: the slow pass (mm/s; 0 = one pass) and how far
#: above the first trigger it starts (mm).
DEFAULT_SECOND_SPEED = 1.0
DEFAULT_SECOND_RETRACT = 1.0
#: Further lift, 0.5 mm at a time, for a probe still triggered before the slow pass.
MAX_EXTRA_RELEASE_MM = 3.0
#: The slow pass may go this far below the first trigger before it counts as missed.
SECOND_PASS_OVERTRAVEL_MM = 1.0

#: The probe latch's HAL signal (``RemoraRouterMapper.PROBE_LATCH_SIGNAL``):
#: Z's step count at the trigger edge * 4 + captures (0..3).
LATCH_SIGNAL = "probe-latch"
#: The latched height may differ from LinuxCNC's by at most this (mm); else
#: something is off and LinuxCNC's value is used.
LATCH_SANITY_MM = 0.5


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


@dataclass(frozen=True)
class ProbeSettings:
    """``[probe] second_speed`` / ``second_retract`` (two-pass probing)."""
    second_speed: float = DEFAULT_SECOND_SPEED
    second_retract: float = DEFAULT_SECOND_RETRACT

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ProbeSettings":
        probe: Dict[str, Any] = payload.get("probe") if isinstance(payload.get("probe"), dict) else {}
        speed = probe.get("second_speed")
        retract = probe.get("second_retract")
        return cls(
            second_speed=DEFAULT_SECOND_SPEED if speed is None else float(speed),
            second_retract=DEFAULT_SECOND_RETRACT if retract is None else float(retract),
        )


def decode_latch(value: Optional[float]) -> Optional[tuple[int, int]]:
    """The latch's process variable -> ``(step count, captures 0..3)``."""
    if value is None:
        return None
    try:
        raw = int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return None
    captures = raw & 3
    return (raw - captures) // 4, captures


class ProbeLatch:
    """Reads the board's probe latch (Remora "Probe Latch") and turns Z's
    latched step count into machine Z.

    ``joint`` is Z's (first) joint, ``scale`` its steps per mm (the INI's
    ``[JOINT_n] SCALE``); axis Z = joint position + (the axis - joint offset
    while standing still, e.g. an external offset)."""

    def __init__(self, joint: Optional[int], scale: Optional[float],
                 read: Optional[Callable[[str], Any]] = None) -> None:
        self.joint = joint
        self.scale = scale
        self._read = read
        #: Whether the last :meth:`trigger_z` used the latch (for reports).
        self.last_used = False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ProbeLatch":
        joint = None
        for axis in payload.get("axes") or []:
            if isinstance(axis, dict) and str(axis.get("id", "")).lower() == "z" and axis.get("joint_numbers"):
                joint = int(axis["joint_numbers"][0])
        scale = None
        if joint is not None:
            from services.calibration.CalibrationService import ini_value

            scale = ini_value(f"JOINT_{joint}", "SCALE")
        return cls(joint, scale)

    def _value(self) -> Any:
        if self._read is not None:
            return self._read(LATCH_SIGNAL)
        from hardware.Connection import read_hal_pin

        return read_hal_pin(LATCH_SIGNAL)

    def captures(self) -> Optional[int]:
        """The capture counter now (``None``: no latch)."""
        if self.joint is None or not self.scale:
            return None
        decoded = decode_latch(self._value())
        return decoded[1] if decoded else None

    def trigger_z(self, stat: Any, captures_before: Optional[int], fallback_z: float) -> float:
        """The latched trigger height when the latch captured since
        ``captures_before`` and agrees with LinuxCNC's ``fallback_z``."""
        self.last_used = False
        if captures_before is None or self.joint is None or not self.scale:
            return fallback_z
        decoded = decode_latch(self._value())
        if decoded is None or decoded[1] == captures_before:
            return fallback_z
        joints: Any = getattr(stat, "joint_actual_position", None)
        axes: Any = getattr(stat, "actual_position", None)
        try:
            offset = float(axes[2]) - float(joints[self.joint])
        except (TypeError, IndexError, ValueError):
            return fallback_z
        latched = decoded[0] / float(self.scale) + offset
        if abs(latched - fallback_z) > LATCH_SANITY_MM:
            import logging

            logging.getLogger("backend.services.motion.Probing").warning(
                "probe latch Z%.4f is %.3f mm from LinuxCNC's Z%.4f: using LinuxCNC's", latched,
                latched - fallback_z, fallback_z)
            return fallback_z
        self.last_used = True
        return latched


@dataclass(frozen=True)
class ProbeReading:
    """One probed point: the height (slow pass, latched when possible), the
    fast pass's, and whether the board's latch gave it."""
    z: float
    first_z: float
    latched: bool
    passes: int


def _probe_once(stat: Any, from_z: float, bottom: float, speed: float, latch: Optional[ProbeLatch],
                where: str) -> float:
    before = latch.captures() if latch is not None else None
    mdi(stat, "G91")
    try:
        mdi(stat, f"G38.2 Z-{probe_distance(from_z, bottom):.4f} F{speed * 60.0:.1f}")
    finally:
        mdi(stat, "G90")
    stat.poll()
    if not getattr(stat, "probe_tripped", False):
        raise ProbeError(f"the probe did not trigger{where} above Z{bottom:g}.")
    fallback = float(stat.probed_position[2])
    return latch.trigger_z(stat, before, fallback) if latch is not None else fallback


def probe_down(stat: Any, from_z: float, bottom: float, speed: float, *,
               settings: ProbeSettings = ProbeSettings(), latch: Optional[ProbeLatch] = None,
               where: str = "") -> ProbeReading:
    """Probe down from machine ``from_z`` (the probe released): fast at
    ``speed``, then — unless ``second_speed`` is 0 or not slower — back up
    ``second_retract`` and slowly again. The machine is left at the last
    stop position (below the trigger)."""
    first = _probe_once(stat, from_z, bottom, speed, latch, where)
    used = bool(latch and latch.last_used)
    if settings.second_speed <= 0 or settings.second_speed >= speed:
        return ProbeReading(first, first, used, 1)
    start = first + settings.second_retract
    mdi(stat, f"G53 G0 Z{start:.4f}")
    extra = 0.0
    while wait_released() is False:
        if extra >= MAX_EXTRA_RELEASE_MM:
            raise ProbeError(
                f"the probe is still triggered {settings.second_retract + extra:g} mm above where it triggered"
                f"{where} — raise [probe] second_retract above its release point.")
        extra += 0.5
        start += 0.5
        mdi(stat, f"G53 G0 Z{start:.4f}")
    floor = max(bottom, first - SECOND_PASS_OVERTRAVEL_MM)
    try:
        second = _probe_once(stat, start, floor, settings.second_speed, latch, where)
    except ProbeError as exc:
        raise ProbeError(f"{exc} (the slow pass, {SECOND_PASS_OVERTRAVEL_MM:g} mm below the fast one's trigger)") \
            from exc
    return ProbeReading(second, first, bool(latch and latch.last_used), 2)


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
    settings: ProbeSettings = ProbeSettings(),
    latch: Optional[ProbeLatch] = None,
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
        reading = probe_down(stat, safe_z, bottom, probe_mm_s, settings=settings, latch=latch,
                             where=f" at X{x:g} Y{y:g}")
        heights.append(reading.z - offsets.z)
        mdi(stat, f"G53 G0 Z{safe_z:.4f}")
        if progress is not None:
            progress(k, heights[-1])
    return heights


__all__ = [
    "LATCH_SIGNAL", "LIMIT_MARGIN_MM", "PROBE_SIGNAL", "ProbeError", "ProbeLatch", "ProbeOffsets", "ProbeReading",
    "ProbeSettings", "decode_latch", "mdi", "probe_distance", "probe_down", "probe_points", "probe_triggered",
    "wait_released",
]
