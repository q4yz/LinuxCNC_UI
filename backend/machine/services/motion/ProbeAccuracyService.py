"""``PROBE_ACCURACY`` — Klipper's probe repeatability test: probe the bed
at the current X, Y ``SAMPLES`` times (retracting ``SAMPLE_RETRACT_DIST``
between) and report maximum, minimum, range, average, median and standard
deviation in the console (each sample under DEBUG, the result under INFO).

``PROBE_ACCURACY [SAMPLES=10] [SAMPLE_RETRACT_DIST=2] [PROBE_SPEED=5]``
— MDI, a macro line. The probe move is relative (LinuxCNC allows
``G53`` with ``G0`` / ``G1`` only), down to ``[stepper_z] position_min``;
between samples Z goes to the absolute machine height trigger point +
``SAMPLE_RETRACT_DIST`` (``G53 G0``). Before each probe move the probe
must report released (:func:`services.motion.Probing.wait_released`): one that
is still triggered would otherwise "trip" at the start of the move.
Z must be homed.
"""
from __future__ import annotations

import logging
import re
import statistics
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from exceptions import BadRequestError, ConflictError
from hardware import get_stat_channel
from hardware.Connection import MachineState
from services.machine.ConsoleLogger import LogLevel, get_console_logger
from services.machine.HardwareConfigService import HardwareConfigService
from services.motion.Probing import (
    LIMIT_MARGIN_MM,
    ProbeError,
    ProbeLatch,
    ProbeSettings,
    mdi,
    probe_down,
    wait_released,
)

logger = logging.getLogger("backend.services.motion.ProbeAccuracyService")

COMMAND = "PROBE_ACCURACY"
MAX_SAMPLES = 100
#: A sample this close below its start height tripped where the move began.
INSTANT_TRIP_MM = 0.005
#: How much further than SAMPLE_RETRACT_DIST to back up for a probe that is
#: still triggered, 1 mm at a time, before giving up (mm).
MAX_EXTRA_RETRACT_MM = 8.0
_PARAM = re.compile(r"([A-Za-z_]+)\s*=\s*(\S+)")


class ProbeAccuracyError(RuntimeError):
    """Why the test stopped."""


#: The Remora SPI driver's counters (``remora-spi.c``): replies with a bad
#: header / count, and the longest run of them since start.
SPI_BAD_PINS = ("remora.SPI-bad-header", "remora.SPI-bad-count")
SPI_RUN_MAX_PIN = "remora.SPI-bad-run-max"


def spi_counters() -> Optional[Dict[str, int]]:
    """``{"bad": ..., "run_max": ...}``, or ``None`` without a Remora SPI board."""
    from hardware.Connection import read_hal_pin

    values = [read_hal_pin(p) for p in (*SPI_BAD_PINS, SPI_RUN_MAX_PIN)]
    if any(v is None for v in values):
        return None
    try:
        return {"bad": int(values[0]) + int(values[1]), "run_max": int(values[2])}
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class ProbeAccuracyRequest:
    samples: int = 10
    retract: float = 2.0
    speed: float = 5.0


@dataclass(frozen=True)
class ProbeAccuracyResult:
    samples: List[float]

    @property
    def maximum(self) -> float:
        return max(self.samples)

    @property
    def minimum(self) -> float:
        return min(self.samples)

    @property
    def range(self) -> float:
        return self.maximum - self.minimum

    @property
    def average(self) -> float:
        return statistics.fmean(self.samples)

    @property
    def median(self) -> float:
        return statistics.median(self.samples)

    @property
    def stddev(self) -> float:
        # population standard deviation, as Klipper reports it
        return statistics.pstdev(self.samples)

    def summary(self) -> str:
        return (
            f"{COMMAND} results ({len(self.samples)} samples): maximum {self.maximum:.6f}, "
            f"minimum {self.minimum:.6f}, range {self.range:.6f}, average {self.average:.6f}, "
            f"median {self.median:.6f}, standard deviation {self.stddev:.6f} mm"
        )


def parse_command(line: str) -> Optional[ProbeAccuracyRequest]:
    """``PROBE_ACCURACY SAMPLES=5`` -> a request; ``None`` for another
    line. Raises ``BadRequestError`` for a bad parameter."""
    text = line.split(";", 1)[0].strip()
    head = text.split(None, 1)[0].upper() if text else ""
    if head != COMMAND:
        return None
    params = {k.upper(): v for k, v in _PARAM.findall(text[len(COMMAND):])}
    try:
        request = ProbeAccuracyRequest(
            samples=int(params.get("SAMPLES", 10)),
            retract=float(params.get("SAMPLE_RETRACT_DIST", 2.0)),
            speed=float(params.get("PROBE_SPEED", 5.0)),
        )
    except ValueError as exc:
        raise BadRequestError(f"{COMMAND}: {exc}") from exc
    if not 1 <= request.samples <= MAX_SAMPLES:
        raise BadRequestError(f"{COMMAND}: SAMPLES must be 1 ... {MAX_SAMPLES}.")
    if request.retract <= 0 or request.speed <= 0:
        raise BadRequestError(f"{COMMAND}: SAMPLE_RETRACT_DIST and PROBE_SPEED must be above 0.")
    return request


class ProbeAccuracyService:
    def __init__(self, config: Optional[HardwareConfigService] = None) -> None:
        self._config = config or HardwareConfigService()
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self.last_result: Optional[ProbeAccuracyResult] = None
        self._warned_release = False

    def is_running(self) -> bool:
        worker = self._worker
        return worker is not None and worker.is_alive()

    def join(self, timeout: Optional[float] = None) -> None:
        worker = self._worker
        if worker is not None:
            worker.join(timeout)

    def start(self, request: ProbeAccuracyRequest, busy: bool = False) -> None:
        """Check and run on a worker thread (MDI); returns at once."""
        self._check_machine(get_stat_channel())
        if busy:
            raise ConflictError("A macro, the homing routine or probing is running.")
        with self._lock:
            if self.is_running():
                raise ConflictError(f"{COMMAND} is already running.")
            self._worker = threading.Thread(target=self._run_worker, args=(request,), name="probe-accuracy", daemon=True)
            self._worker.start()

    def _run_worker(self, request: ProbeAccuracyRequest) -> None:
        try:
            self.run(get_stat_channel(), request)
        except ProbeAccuracyError as exc:
            get_console_logger().log_event(f"{COMMAND} aborted: {exc}", level=LogLevel.ERROR, source="CMD")
        except Exception as exc:  # noqa: BLE001 - report, don't die silently
            logger.exception("%s crashed: %s", COMMAND, exc)
            get_console_logger().log_event(f"{COMMAND} aborted: {exc}", level=LogLevel.ERROR, source="CMD")

    def run_command(self, line: str, stat: Any) -> bool:
        """A ``PROBE_ACCURACY`` line on the calling worker (a macro):
        run it and ``True``; ``False`` for another line."""
        request = parse_command(line)
        if request is None:
            return False
        self.run(stat, request)
        return True

    def run(self, stat: Any, request: ProbeAccuracyRequest) -> ProbeAccuracyResult:
        self._check_machine(stat)
        console = get_console_logger()
        self._warned_release = False
        bottom = self._probe_bottom()
        stat.poll()
        start_z = self._commanded_z(stat)
        if start_z <= bottom + LIMIT_MARGIN_MM:
            raise ProbeAccuracyError(f"Z{start_z:g} is not above the lowest Z{bottom:g} — move Z up first.")
        console.log_event(
            f"{COMMAND}: {request.samples} samples at the current X Y, retract {request.retract:g} mm, "
            f"{request.speed:g} mm/s.",
            level=LogLevel.DEBUG, source="CMD",
        )
        samples: List[float] = []
        payload = self._config.load_payload()
        settings = ProbeSettings.from_payload(payload)
        latch = ProbeLatch.from_payload(payload)
        spi_before = spi_counters()
        latched = 0
        passes = 1
        try:
            mdi(stat, "G90")
            for k in range(request.samples):
                start_z = self._released_start(stat, start_z, request.retract, console)
                try:
                    reading = probe_down(stat, start_z, bottom, request.speed, settings=settings, latch=latch,
                                         where=f" (sample {k + 1})")
                except ProbeError as exc:
                    raise ProbeAccuracyError(str(exc)) from exc
                latched += reading.latched
                passes = reading.passes
                z = reading.z
                if reading.first_z >= start_z - INSTANT_TRIP_MM:
                    # Tripped where the move began: still triggered from the
                    # last sample, not the bed (see Probing.wait_released).
                    raise ProbeAccuracyError(
                        f"sample {k + 1} triggered at its start (Z{start_z:.3f}): the probe was still triggered. "
                        f"Its release point is above SAMPLE_RETRACT_DIST={request.retract:g} mm — use a larger one."
                    )
                samples.append(z)
                console.log_event(f"{COMMAND}: sample {k + 1}/{request.samples} at Z {z:.6f}", level=LogLevel.DEBUG,
                                  source="CMD")
                # Back up to an absolute height above the trigger point: the
                # next probe distance is known, not read back from LinuxCNC.
                start_z = z + request.retract
                mdi(stat, f"G53 G0 Z{start_z:.4f}")
        except ProbeError as exc:
            raise ProbeAccuracyError(str(exc)) from exc
        finally:
            try:
                mdi(stat, "G90")
            except ProbeError:
                pass
        result = ProbeAccuracyResult(samples)
        self.last_result = result
        from services.calibration.CalibrationService import record

        record("probe_accuracy", f"range {result.range:.4f} mm, std dev {result.stddev:.4f} mm "
                                 f"({len(result.samples)} samples)")
        note = self._method_note(request, settings, passes, latched, len(samples), spi_before)
        console.log_event(f"{result.summary()}. {note}", level=LogLevel.INFO, source="CMD")
        return result

    def _released_start(self, stat: Any, start_z: float, retract: float, console: Any) -> float:
        """``start_z``, or higher: while the probe still reports triggered,
        back up another millimetre (up to :data:`MAX_EXTRA_RETRACT_MM`) and
        say once which retract it needs."""
        extra = 0.0
        while wait_released() is False:
            if extra >= MAX_EXTRA_RETRACT_MM:
                raise ProbeAccuracyError(
                    f"the probe is still triggered {retract + extra:g} mm above where it last triggered (Z{start_z:.3f}) "
                    "— check the probe and its wiring."
                )
            extra += 1.0
            start_z += 1.0
            mdi(stat, f"G53 G0 Z{start_z:.4f}")
        if extra and not self._warned_release:
            self._warned_release = True
            console.log_event(
                f"{COMMAND}: the probe released only {retract + extra:g} mm above its trigger point; continuing from "
                f"there (use SAMPLE_RETRACT_DIST={retract + extra:g} to skip this).",
                level=LogLevel.WARNING, source="CMD",
            )
        return start_z

    @staticmethod
    def _method_note(request: ProbeAccuracyRequest, settings: ProbeSettings, passes: int, latched: int,
                     samples: int, spi_before: Optional[Dict[str, int]]) -> str:
        """How the samples were taken, and the SPI link's bad replies meanwhile
        (a broken reply holds the probe input: a late trigger)."""
        how = (f"two passes ({request.speed:g} then {settings.second_speed:g} mm/s)" if passes == 2
               else f"one pass at {request.speed:g} mm/s")
        where = ("the board's latch (exact to 25 us)" if latched == samples
                 else f"the board's latch for {latched} of {samples}, LinuxCNC's 1 ms sample for the rest" if latched
                 else "LinuxCNC's 1 ms sample (no probe latch on the board)")
        note = f"Probed in {how}; trigger heights from {where}"
        after = spi_counters()
        if spi_before is not None and after is not None:
            bad = after["bad"] - spi_before["bad"]
            note += (f"; SPI: {bad} bad replies during the test (longest run {after['run_max']} frames — the probe "
                     "input is held meanwhile)" if bad else "; SPI: no bad replies")
        return note + "."

    @staticmethod
    def _commanded_z(stat: Any) -> float:
        """Machine Z as commanded (``stat.position``): the feedback
        (``actual_position``) is quantised to steps and put the target a
        hair past the soft limit."""
        position = getattr(stat, "position", None) or stat.actual_position
        return float(position[2])

    def _probe_bottom(self) -> float:
        payload: Dict[str, Any] = self._config.load_payload()
        for section in ("z_tilt", "bed_mesh"):
            value = payload.get(section)
            if isinstance(value, dict) and value.get("probe_min_z") is not None:
                return float(value["probe_min_z"])
        for axis in payload.get("axes") or []:
            if isinstance(axis, dict) and str(axis.get("id", "")).lower() == "z":
                return float(axis.get("position_min") or 0.0)
        return 0.0

    def _check_machine(self, stat: Any, command: str = COMMAND) -> None:
        if not self._config.load_payload().get("probe"):
            raise BadRequestError(f"{command} needs a [probe] section.")
        if stat is None:
            raise BadRequestError(f"Cannot run {command}: LinuxCNC is not running.")
        stat.poll()
        if stat.estop:
            raise BadRequestError(f"Cannot run {command} while the machine is in E-STOP.")
        if stat.task_state != MachineState.ON.value:
            raise BadRequestError(f"Turn the machine on before {command}.")
        homed = list(getattr(stat, "homed", ()) or ())
        joints = [int(j) for a in self._config.get_axes() if str(a.get("id", "")).lower() == "z"
                  for j in a.get("joint_numbers") or []]
        missing = [j for j in joints if not (j < len(homed) and homed[j])]
        if missing:
            raise BadRequestError(f"Home Z first (joint(s) {', '.join(map(str, missing))} not homed).")


_SERVICE: Optional[ProbeAccuracyService] = None


def get_probe_accuracy_service() -> ProbeAccuracyService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = ProbeAccuracyService()
    return _SERVICE


__all__ = [
    "COMMAND", "ProbeAccuracyError", "ProbeAccuracyRequest", "ProbeAccuracyResult", "ProbeAccuracyService",
    "get_probe_accuracy_service", "parse_command",
]
