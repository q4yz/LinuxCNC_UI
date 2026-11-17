"""``PID_CALIBRATE HEATER=<name> TARGET=<°C>`` — Klipper's relay autotune on
a PID heater.

The heater's HAL loop has a ``tune-<id>`` mux between the PID output and the
heater (`HeaterHalMapper`): while ``webgui.tune-<id>-enable`` is on (and the
board answers, out of E-stop) the heater gets ``webgui.tune-<id>-duty``
instead. This service switches full power on below ``TARGET - 5`` and off
above ``TARGET`` (a relay), records the temperature peaks and, after 12 of
them, computes Ziegler-Nichols gains (Klipper's ``calc_pid``)::

    Ku = 4 * max_duty / (pi * amplitude)      Tu = the oscillation period
    Kp = 0.6 * Ku    Ki = Kp / (0.5 * Tu)    Kd = Kp * 0.125 * Tu

The duty is in percent (``PIDcontroller``'s ``CVmax`` 100 * max_power), so
the gains fit ``pid_Kp`` / ``pid_Ki`` / ``pid_Kd`` of this machine's profile
as they are: Klipper's own numbers (base 255) are 2.55 times larger.
Nothing is written: the console prints the lines for the profile.
"""
from __future__ import annotations

import logging
import math
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple

from dtos.pins.HalPin import HalDataType
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from exceptions import BadRequestError, ConflictError

logger = logging.getLogger("backend.services.pid_calibrate")

COMMAND = "PID_CALIBRATE"
TUNE_DELTA = 5.0          # °C below the target the relay switches on again
PEAKS = 12
#: Abort: this far above the target, or no new peak for this long.
OVERSHOOT_LIMIT = 25.0
PEAK_TIMEOUT_S = 600.0
POLL_S = 0.1
_PARAM = re.compile(r"([A-Za-z_]+)\s*=\s*([^\s]+)")


class PidCalibrateError(RuntimeError):
    """The autotune stopped (a limit, the machine, the heater)."""


@dataclass
class RelayTuner:
    """The relay test, fed one reading at a time (no I/O: testable)."""

    target: float
    max_duty: float
    delta: float = TUNE_DELTA
    heating: bool = True
    peak: float = -1e9
    peak_time: float = 0.0
    peaks: List[Tuple[float, float]] = field(default_factory=list)

    def update(self, temp: float, now: float) -> float:
        """The duty for this reading."""
        if self.heating:
            if temp >= self.target:
                self.heating = False
                self._record()
                self.peak = temp
        elif temp <= self.target - self.delta:
            self.heating = True
            self._record()
            self.peak = temp
        if (self.heating and temp < self.peak) or (not self.heating and temp > self.peak):
            self.peak, self.peak_time = temp, now
        return self.max_duty if self.heating else 0.0

    def _record(self) -> None:
        # the first switch has no extreme of a full half-cycle behind it
        if self.peak > -1e8:
            self.peaks.append((self.peak, self.peak_time))

    @property
    def done(self) -> bool:
        return len(self.peaks) >= PEAKS

    def result(self) -> Tuple[float, float, float]:
        """(Kp, Ki, Kd) from the last four peaks (high, low, high, low)."""
        if len(self.peaks) < 4:
            raise PidCalibrateError("not enough temperature peaks")
        last = self.peaks[-4:]
        temps = [t for t, _ in last]
        amplitude = 0.5 * (max(temps) - min(temps))
        times = [ts for _, ts in last]
        tu = 0.5 * ((times[2] - times[0]) + (times[3] - times[1]))
        if amplitude <= 0 or tu <= 0:
            raise PidCalibrateError("no oscillation measured")
        ku = 4.0 * self.max_duty / (math.pi * amplitude)
        kp = 0.6 * ku
        ti, td = 0.5 * tu, 0.125 * tu
        return kp, kp / ti, kp * td


def parse_command(line: str) -> Optional[dict[str, str]]:
    """``PID_CALIBRATE HEATER=extruder TARGET=210`` -> its parameters
    (upper-case keys); ``None`` for another line."""
    text = line.split(";", 1)[0].strip()
    head = text.split(None, 1)[0].upper() if text else ""
    if head != COMMAND:
        return None
    return {k.upper(): v for k, v in _PARAM.findall(text[len(head):])}


class PidCalibrateService:
    def __init__(self) -> None:
        self._pins: dict[str, ReadWriteDynamicHalPin[Any]] = {}
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.last: dict[str, Any] = {}

    # -- setup -------------------------------------------------------------- #

    @staticmethod
    def _heaters() -> List[dict[str, Any]]:
        """The profile's PID heaters (extruders, beds)."""
        from services.HardwareConfigService import HardwareConfigService

        return [t for t in HardwareConfigService().load_payload().get("tools") or []
                if isinstance(t, dict) and t.get("type") in ("extruder", "heated_bed")
                and (t.get("control") or "pid").strip().lower() == "pid"]

    def preload_hal_pins(self) -> None:
        for heater in self._heaters():
            hid = str(heater["id"])
            self._pins[f"{hid}-enable"] = ReadWriteDynamicHalPin(
                f"tune-{hid}-enable", HalDataType.BIT, f"PID_CALIBRATE: {hid} on the relay")
            self._pins[f"{hid}-duty"] = ReadWriteDynamicHalPin(
                f"tune-{hid}-duty", HalDataType.FLOAT, f"PID_CALIBRATE: {hid} duty (%)")
        for heater in self._heaters():
            self._release(str(heater["id"]))

    def _write(self, key: str, value: Any) -> None:
        handle = self._pins.get(key)
        if handle is not None:
            handle.set_value(value)

    def _release(self, hid: str) -> None:
        self._write(f"{hid}-duty", 0.0)
        self._write(f"{hid}-enable", False)

    def resolve(self, name: str) -> dict[str, Any]:
        """``HEATER=``: a tool id, or Klipper's ``extruder`` / ``heater_bed``."""
        heaters = self._heaters()
        wanted = name.strip().lower()
        for heater in heaters:
            if str(heater["id"]).lower() == wanted:
                return heater
        kind = {"extruder": "extruder", "heater_bed": "heated_bed"}.get(wanted)
        matches = [h for h in heaters if h.get("type") == kind]
        if matches:
            return matches[0]
        names = ", ".join(str(h["id"]) for h in heaters) or "none"
        raise BadRequestError(f"{COMMAND}: no PID heater {name!r} (the profile's: {names}).")

    # -- run ---------------------------------------------------------------- #

    def is_running(self) -> bool:
        worker = self._worker
        return worker is not None and worker.is_alive()

    def stop(self) -> None:
        self._stop.set()

    def run_command(self, line: str, busy: bool = False) -> bool:
        params = parse_command(line)
        if params is None:
            return False
        if "HEATER" not in params or "TARGET" not in params:
            raise BadRequestError(f"{COMMAND} HEATER=<extruder|heater_bed|id> TARGET=<°C>.")
        heater = self.resolve(params["HEATER"])
        try:
            target = float(params["TARGET"])
        except ValueError as exc:
            raise BadRequestError(f"{COMMAND}: TARGET {params['TARGET']!r} is not a number.") from exc
        max_temp = heater.get("max_temp")
        if target <= 30 or (max_temp is not None and target + TUNE_DELTA > float(max_temp)):
            raise BadRequestError(f"{COMMAND}: TARGET {target:g} °C is outside 30 … max_temp - {TUNE_DELTA:g}.")
        if busy:
            raise ConflictError("A macro, the homing routine or probing is running.")
        self._check_machine()
        with self._lock:
            if self.is_running():
                raise ConflictError(f"{COMMAND} is already running.")
            self._stop.clear()
            self._worker = threading.Thread(target=self._run_worker, args=(heater, target), name="pid-calibrate",
                                            daemon=True)
            self._worker.start()
        return True

    @staticmethod
    def _check_machine() -> None:
        from hardware import get_stat_channel

        stat = get_stat_channel()
        if stat is None:
            raise BadRequestError("LinuxCNC is not running.")
        stat.poll()
        if stat.estop:
            raise BadRequestError("Release the E-stop first (the heaters are off in E-stop).")

    def _run_worker(self, heater: dict[str, Any], target: float) -> None:
        from hardware.Connection import read_hal_pin
        from services.ConsoleLogger import LogLevel, get_console_logger

        console = get_console_logger()
        try:
            kp, ki, kd = self.calibrate(heater, target, lambda: read_hal_pin(f"PID-{heater['id']}.PV"),
                                        time.monotonic, time.sleep, console.log_event, estop=_in_estop)
            from services.CalibrationService import record_pid

            record_pid(str(heater["id"]), kp, ki, kd)
        except PidCalibrateError as exc:
            console.log_event(f"{COMMAND} aborted: {exc}", level=LogLevel.ERROR, source="CMD")
        except Exception as exc:  # noqa: BLE001 - a worker must not die silently
            logger.exception("PID_CALIBRATE failed")
            console.log_event(f"{COMMAND} aborted: {exc}", level=LogLevel.ERROR, source="CMD")

    def calibrate(self, heater: dict[str, Any], target: float, read: Callable[[], Any],
                  clock: Callable[[], float], sleep: Callable[[float], None],
                  log: Callable[..., None],
                  estop: Callable[[], bool] = lambda: False) -> Tuple[float, float, float]:
        """The relay test on the calling thread; the heater is handed back
        to its PID loop in every case."""
        from services.ConsoleLogger import LogLevel

        hid = str(heater["id"])
        tuner = RelayTuner(target, 100.0 * float(heater.get("max_power") or 1.0))
        log(f"{COMMAND}: {hid} at {target:g} °C — the heater cycles around it ({PEAKS} peaks, minutes).",
            level=LogLevel.INFO, source="CMD")
        start = last_peak = clock()
        try:
            self._write(f"{hid}-duty", tuner.max_duty)
            self._write(f"{hid}-enable", True)
            while not tuner.done:
                if self._stop.is_set():
                    raise PidCalibrateError("stopped")
                if estop():
                    raise PidCalibrateError("E-stop")
                raw = read()
                if raw is None:
                    raise PidCalibrateError(f"cannot read {hid}'s temperature")
                temp, now = float(raw), clock()
                if temp > target + OVERSHOOT_LIMIT:
                    raise PidCalibrateError(f"{temp:.1f} °C is {OVERSHOOT_LIMIT:g} °C over the target")
                count = len(tuner.peaks)
                self._write(f"{hid}-duty", tuner.update(temp, now))
                if len(tuner.peaks) != count:
                    last_peak = now
                    log(f"{COMMAND}: peak {len(tuner.peaks)}/{PEAKS} at {tuner.peaks[-1][0]:.1f} °C.",
                        level=LogLevel.DEBUG, source="CMD")
                elif now - last_peak > PEAK_TIMEOUT_S:
                    raise PidCalibrateError(f"{hid} did not reach {target:g} °C in {PEAK_TIMEOUT_S / 60:g} min")
                sleep(POLL_S)
        finally:
            self._release(hid)
        kp, ki, kd = tuner.result()
        self.last = {"heater": hid, "target": target, "kp": kp, "ki": ki, "kd": kd,
                     "duration_s": clock() - start}
        log(f"{COMMAND}: {hid} pid_Kp={kp:.3f} pid_Ki={ki:.3f} pid_Kd={kd:.3f} — saved to calibration.ini and "
            "active now (the Calibration tab's Clear goes back to the profile's).", level=LogLevel.INFO, source="CMD")
        return kp, ki, kd


def _in_estop() -> bool:
    from hardware import get_stat_channel

    stat = get_stat_channel()
    if stat is None:
        return True
    stat.poll()
    return bool(stat.estop)


_SERVICE: Optional[PidCalibrateService] = None


def get_pid_calibrate_service() -> PidCalibrateService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = PidCalibrateService()
    return _SERVICE


__all__ = ["PidCalibrateError", "PidCalibrateService", "RelayTuner", "get_pid_calibrate_service", "parse_command"]
