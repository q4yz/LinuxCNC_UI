"""``PROBE_ACCURACY`` — Klipper's probe repeatability test: probe the bed
at the current X, Y ``SAMPLES`` times (retracting ``SAMPLE_RETRACT_DIST``
between) and report maximum, minimum, range, average, median and standard
deviation in the console (each sample under DEBUG, the result under INFO).

``PROBE_ACCURACY [SAMPLES=10] [SAMPLE_RETRACT_DIST=2] [PROBE_SPEED=5]``
— MDI, a macro line. The probe move is relative (LinuxCNC allows
``G53`` with ``G0`` / ``G1`` only), down to ``[stepper_z] position_min``.
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
from services.ConsoleLogger import LogLevel, get_console_logger
from services.HardwareConfigService import HardwareConfigService
from services.Probing import ProbeError, mdi

logger = logging.getLogger("backend.services.ProbeAccuracyService")

COMMAND = "PROBE_ACCURACY"
MAX_SAMPLES = 100
_PARAM = re.compile(r"([A-Za-z_]+)\s*=\s*(\S+)")


class ProbeAccuracyError(RuntimeError):
    """Why the test stopped."""


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
        bottom = self._probe_bottom()
        stat.poll()
        start_z = float(stat.actual_position[2])
        if start_z <= bottom:
            raise ProbeAccuracyError(f"Z{start_z:g} is not above the lowest Z{bottom:g} — move Z up first.")
        console.log_event(
            f"{COMMAND}: {request.samples} samples at the current X Y, retract {request.retract:g} mm, "
            f"{request.speed:g} mm/s.",
            level=LogLevel.DEBUG, source="CMD",
        )
        samples: List[float] = []
        try:
            mdi(stat, "G91")
            for k in range(request.samples):
                stat.poll()
                distance = float(stat.actual_position[2]) - bottom
                mdi(stat, f"G38.2 Z-{distance:.4f} F{request.speed * 60.0:.1f}")
                stat.poll()
                if not getattr(stat, "probe_tripped", False):
                    raise ProbeAccuracyError(f"the probe did not trigger above Z{bottom:g} (sample {k + 1}).")
                z = float(stat.probed_position[2])
                samples.append(z)
                console.log_event(f"{COMMAND}: sample {k + 1}/{request.samples} at Z {z:.6f}", level=LogLevel.DEBUG,
                                  source="CMD")
                mdi(stat, f"G0 Z{request.retract:.4f}")
        except ProbeError as exc:
            raise ProbeAccuracyError(str(exc)) from exc
        finally:
            try:
                mdi(stat, "G90")
            except ProbeError:
                pass
        result = ProbeAccuracyResult(samples)
        self.last_result = result
        console.log_event(result.summary(), level=LogLevel.INFO, source="CMD")
        return result

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

    def _check_machine(self, stat: Any) -> None:
        if not self._config.load_payload().get("probe"):
            raise BadRequestError(f"{COMMAND} needs a [probe] section.")
        if stat is None:
            raise BadRequestError(f"Cannot run {COMMAND}: LinuxCNC is not running.")
        stat.poll()
        if stat.estop:
            raise BadRequestError(f"Cannot run {COMMAND} while the machine is in E-STOP.")
        if stat.task_state != MachineState.ON.value:
            raise BadRequestError(f"Turn the machine on before {COMMAND}.")
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
