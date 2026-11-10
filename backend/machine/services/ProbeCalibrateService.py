"""``PROBE_CALIBRATE`` — Klipper's paper test for ``[probe] z_offset``.

1. ``PROBE_CALIBRATE [SPEED=5]`` (MDI): probe the bed at the current X, Y,
   lift 5 mm, move the nozzle over the spot the probe touched (``x_offset``,
   ``y_offset``) and lower it back to the probe's trigger height.
2. Lower the nozzle until a sheet of paper just drags: the Z jog buttons
   or ``TESTZ Z=-0.1`` (relative, mm; ``TESTZ Z=0.05`` back up). Each
   ``TESTZ`` logs the ``z_offset`` the nozzle's height would give.
3. ``ACCEPT``: ``z_offset = trigger Z - nozzle Z``, logged under INFO, to
   put into the machine's ``.cfg`` (``[probe] z_offset``). ``ABORT`` ends
   the test without a value.

Bed mesh compensation is switched off for the test (its Z offset would
move the nozzle with X, Y). Z must be homed.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

from exceptions import BadRequestError, ConflictError
from hardware import get_stat_channel
from services.ConsoleLogger import LogLevel, get_console_logger
from services.HardwareConfigService import HardwareConfigService
from services.Probing import LIMIT_MARGIN_MM, ProbeError, ProbeOffsets, mdi, probe_distance

logger = logging.getLogger("backend.services.ProbeCalibrateService")

COMMAND = "PROBE_CALIBRATE"
#: The lift between the probe's trigger and the move over the spot.
LIFT_MM = 5.0
#: The largest single ``TESTZ`` step.
MAX_TESTZ_MM = 5.0
_PARAM = re.compile(r"([A-Za-z_]+)\s*=\s*(\S+)")


class ProbeCalibrateError(RuntimeError):
    """Why the test stopped."""


@dataclass(frozen=True)
class Session:
    #: Machine Z (nozzle) when the probe triggered.
    trigger_z: float
    offsets: ProbeOffsets

    def z_offset(self, nozzle_z: float) -> float:
        return self.trigger_z - nozzle_z


def _words(line: str) -> tuple[str, dict[str, str]]:
    text = line.split(";", 1)[0].strip()
    head = text.split(None, 1)[0].upper() if text else ""
    return head, {k.upper(): v for k, v in _PARAM.findall(text[len(head):])}


def _number(command: str, params: dict[str, str], key: str, default: Optional[float] = None) -> float:
    raw = params.get(key)
    if raw is None:
        if default is None:
            raise BadRequestError(f"{command}: {key}=<mm> is missing.")
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise BadRequestError(f"{command}: {key}={raw} is not a number.") from exc


class ProbeCalibrateService:
    def __init__(self, config: Optional[HardwareConfigService] = None) -> None:
        from services.ProbeAccuracyService import ProbeAccuracyService

        self._config = config or HardwareConfigService()
        # the machine checks, the probe's lowest Z, the commanded Z
        self._checks = ProbeAccuracyService(self._config)
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self.session: Optional[Session] = None
        self.last_z_offset: Optional[float] = None

    # -- MDI ----------------------------------------------------------- #

    def is_running(self) -> bool:
        worker = self._worker
        return worker is not None and worker.is_alive()

    def join(self, timeout: Optional[float] = None) -> None:
        worker = self._worker
        if worker is not None:
            worker.join(timeout)

    def run_command(self, line: str, busy: bool = False) -> bool:
        """``PROBE_CALIBRATE`` / ``TESTZ`` / ``ACCEPT`` / ``ABORT`` from MDI:
        ``True`` when it was one (the moves run on a worker thread)."""
        head, params = _words(line)
        if head == COMMAND:
            speed = _number(COMMAND, params, "SPEED", 5.0)
            if speed <= 0:
                raise BadRequestError(f"{COMMAND}: SPEED must be above 0.")
            stat = get_stat_channel()
            self._checks._check_machine(stat, COMMAND)
            self._spawn(busy, lambda: self.start(stat, speed))
            return True
        if head not in ("TESTZ", "ACCEPT", "ABORT"):
            return False
        if self.session is None:
            if head == "ABORT":
                return False  # not ours: nothing to abort here
            raise BadRequestError(f"{head}: no {COMMAND} is running — start one first.")
        if head == "TESTZ":
            delta = _number("TESTZ", params, "Z")
            if not 0 < abs(delta) <= MAX_TESTZ_MM:
                raise BadRequestError(f"TESTZ: Z must be a step of up to ±{MAX_TESTZ_MM:g} mm (not 0).")
            stat = get_stat_channel()
            self._spawn(False, lambda: self.testz(stat, delta))
        elif head == "ACCEPT":
            self.accept(get_stat_channel())
        else:
            self.abort()
        return True

    def _spawn(self, busy: bool, work: Callable[[], Any]) -> None:
        if busy:
            raise ConflictError("A macro, the homing routine or probing is running.")
        with self._lock:
            if self.is_running():
                raise ConflictError(f"{COMMAND} is still moving.")
            self._worker = threading.Thread(target=self._run_worker, args=(work,), name="probe-calibrate",
                                            daemon=True)
            self._worker.start()

    def _run_worker(self, work: Callable[[], Any]) -> None:
        try:
            work()
        except (ProbeCalibrateError, BadRequestError) as exc:
            self.session = None
            detail = getattr(exc, "detail", None) or exc
            get_console_logger().log_event(f"{COMMAND} aborted: {detail}", level=LogLevel.ERROR, source="CMD")
        except Exception as exc:  # noqa: BLE001 - report, don't die silently
            self.session = None
            logger.exception("%s crashed: %s", COMMAND, exc)
            get_console_logger().log_event(f"{COMMAND} aborted: {exc}", level=LogLevel.ERROR, source="CMD")

    # -- the steps (on the calling thread) ------------------------------ #

    def start(self, stat: Any, speed: float = 5.0) -> Session:
        """Probe, lift, move the nozzle over the spot, lower it to the
        trigger height; the session waits for ``TESTZ`` / ``ACCEPT``."""
        self.session = None
        self._checks._check_machine(stat, COMMAND)
        console = get_console_logger()
        offsets = ProbeOffsets.from_payload(self._config.load_payload())
        bottom = self._checks._probe_bottom()
        stat.poll()
        start_z = self._checks._commanded_z(stat)
        if start_z <= bottom + LIMIT_MARGIN_MM:
            raise ProbeCalibrateError(f"Z{start_z:g} is not above the lowest Z{bottom:g} — move Z up first.")
        self._compensation_off(console)
        try:
            mdi(stat, "G91")
            mdi(stat, f"G38.2 Z-{probe_distance(start_z, bottom):.4f} F{speed * 60.0:.1f}")
            stat.poll()
            if not getattr(stat, "probe_tripped", False):
                raise ProbeCalibrateError(f"the probe did not trigger above Z{bottom:g}.")
            trigger_z = float(stat.probed_position[2])
            mdi(stat, f"G0 Z{LIFT_MM:.4f}")
            if offsets.x or offsets.y:
                mdi(stat, f"G0 X{offsets.x:.4f} Y{offsets.y:.4f}")
            mdi(stat, f"G0 Z-{LIFT_MM:.4f}")
        except ProbeError as exc:
            raise ProbeCalibrateError(str(exc)) from exc
        finally:
            try:
                mdi(stat, "G90")
            except ProbeError:
                pass
        self.session = Session(trigger_z, offsets)
        console.log_event(
            f"{COMMAND}: the probe triggered at Z {trigger_z:.4f}; the nozzle is over that spot at the same height. "
            "Lower it with the Z jog or TESTZ Z=-0.1 until a sheet of paper just drags, then ACCEPT (ABORT cancels).",
            level=LogLevel.INFO, source="CMD",
        )
        return self.session

    def testz(self, stat: Any, delta: float) -> float:
        """Move the nozzle ``delta`` mm in Z; the ``z_offset`` it gives."""
        session = self._require_session()
        try:
            mdi(stat, "G91")
            mdi(stat, f"G0 Z{delta:.4f}")
        except ProbeError as exc:
            raise ProbeCalibrateError(str(exc)) from exc
        finally:
            try:
                mdi(stat, "G90")
            except ProbeError:
                pass
        stat.poll()
        nozzle_z = self._checks._commanded_z(stat)
        z_offset = session.z_offset(nozzle_z)
        get_console_logger().log_event(
            f"TESTZ: nozzle at Z {nozzle_z:.4f} -> z_offset {z_offset:.4f} (ACCEPT keeps it).",
            level=LogLevel.INFO, source="CMD",
        )
        return z_offset

    def accept(self, stat: Any) -> float:
        session = self._require_session()
        if self.is_running():
            raise ConflictError(f"{COMMAND} is still moving — ACCEPT once it stopped.")
        stat.poll()
        nozzle_z = self._checks._commanded_z(stat)
        z_offset = session.z_offset(nozzle_z)
        self.session = None
        self.last_z_offset = z_offset
        console = get_console_logger()
        if z_offset <= 0:
            console.log_event(
                f"{COMMAND}: the nozzle (Z {nozzle_z:.4f}) is not below the trigger height (Z "
                f"{session.trigger_z:.4f}): z_offset {z_offset:.4f} — the nozzle must touch the bed after the probe.",
                level=LogLevel.ERROR, source="CMD",
            )
            return z_offset
        console.log_event(
            f"{COMMAND}: z_offset: {z_offset:.3f} — put it in the machine's .cfg ([probe] z_offset: {z_offset:.3f}) "
            "and generate the machine again.",
            level=LogLevel.INFO, source="CMD",
        )
        return z_offset

    def abort(self) -> None:
        self.session = None
        get_console_logger().log_event(f"{COMMAND} aborted: no z_offset taken.", level=LogLevel.INFO, source="CMD")

    # -- helpers ------------------------------------------------------- #

    def _require_session(self) -> Session:
        session = self.session
        if session is None:
            raise ProbeCalibrateError(f"no {COMMAND} is running.")
        return session

    def _compensation_off(self, console: Any) -> None:
        if not self._config.load_payload().get("bed_mesh"):
            return
        from services.BedMeshProbeService import BedMeshError, BedMeshProbeService
        from services.BedMeshService import get_bed_mesh_service

        compensation = get_bed_mesh_service()
        if not compensation.is_enabled():
            return
        compensation.set_enabled(False)
        try:
            BedMeshProbeService._wait_offset_zero()
        except BedMeshError as exc:
            raise ProbeCalibrateError(str(exc)) from exc
        console.log_event(f"{COMMAND}: bed mesh compensation switched off for the test.", level=LogLevel.DEBUG,
                          source="CMD")


_SERVICE: Optional[ProbeCalibrateService] = None


def get_probe_calibrate_service() -> ProbeCalibrateService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = ProbeCalibrateService()
    return _SERVICE


__all__ = [
    "COMMAND", "MAX_TESTZ_MM", "ProbeCalibrateError", "ProbeCalibrateService", "Session",
    "get_probe_calibrate_service",
]
