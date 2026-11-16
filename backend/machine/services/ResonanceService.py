"""Resonance measurement for input shaping (Klipper's ``TEST_RESONANCES`` /
``SHAPER_CALIBRATE``): an ADXL345 on the host's SPI (``[adxl345]``,
``Adxl345``), the test signal from the Remora ``jointshape`` component
(``ShaperService``).

``SHAPER_CALIBRATE [AXIS=X|Y]`` (``TEST_RESONANCES AXIS=...`` the same, one
axis): at the current position the axis vibrates with a sine swept from
``min_freq`` to ``max_freq`` (``hz_per_sec``), ``accel_per_hz`` × f of
acceleration (amplitude a / (2πf)²), while the accelerometer is read. Then
the spectrum (Welch) of the axis' acceleration is scored for every shaper
— Klipper's residual vibration, at damping 0.075 / 0.1 / 0.15 — and the
best frequency per shaper and an overall recommendation go to the console,
as profile lines (``[input_shaper] shaper_type_x: … shaper_freq_x: …``).
``ACCELEROMETER_QUERY`` reads the chip once.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence, Tuple

from exceptions import BadRequestError, ConflictError

logger = logging.getLogger("backend.services.resonance")

SHAPERS = ("zv", "mzv", "zvd", "ei")
TEST_DAMPING = (0.075, 0.1, 0.15)
SHAPER_DAMPING = 0.1
FREQ_STEP = 0.2


def shaper_impulses(kind: str, freq: float, damping: float = SHAPER_DAMPING) -> Tuple[List[float], List[float]]:
    """Amplitudes and times of ``kind`` at ``freq`` (the jointshape
    component's shapers)."""
    df = math.sqrt(1.0 - damping * damping)
    k = math.exp(-damping * math.pi / df)
    td = 1.0 / (freq * df)
    if kind == "zv":
        return [1.0, k], [0.0, 0.5 * td]
    if kind == "zvd":
        return [1.0, 2.0 * k, k * k], [0.0, 0.5 * td, td]
    if kind == "ei":
        v = 0.05
        a1 = 0.25 * (1.0 + v)
        return [a1, 0.5 * (1.0 - v) * k, a1 * k * k], [0.0, 0.5 * td, td]
    k2 = math.exp(-0.75 * damping * math.pi / df)
    a1 = 1.0 - 1.0 / math.sqrt(2.0)
    return [a1, (math.sqrt(2.0) - 1.0) * k2, a1 * k2 * k2], [0.0, 0.375 * td, 0.75 * td]


def residual_vibration(amps: Sequence[float], times: Sequence[float], freqs: Any, damping: float) -> Any:
    """Klipper's estimate: the share of a vibration at ``freqs`` the shaper
    leaves (1 = none removed)."""
    import numpy as np

    a, t = np.array(amps), np.array(times)
    omega = 2.0 * math.pi * np.asarray(freqs)
    w = a * np.exp(np.outer(-damping * omega, t[-1] - t))
    omega_d = omega * math.sqrt(1.0 - damping * damping)
    s = (w * np.sin(np.outer(omega_d, t))).sum(axis=1)
    c = (w * np.cos(np.outer(omega_d, t))).sum(axis=1)
    return np.sqrt(s * s + c * c) / a.sum()


def power_spectrum(values: Sequence[float], rate: float) -> Tuple[Any, Any]:
    """Welch PSD (Hann, 50 % overlap, ~1 s windows): (freqs, psd)."""
    import numpy as np

    x = np.asarray(values, dtype=float)
    x = x - x.mean()
    n = 1 << int(math.log2(max(16, min(len(x), rate))))
    if len(x) < n:
        raise BadRequestError("too few accelerometer samples for a spectrum")
    window = np.hanning(n)
    step = n // 2
    segments = [x[i:i + n] * window for i in range(0, len(x) - n + 1, step)]
    spectra = [np.abs(np.fft.rfft(seg)) ** 2 for seg in segments]
    psd = np.mean(spectra, axis=0) / (rate * (window ** 2).sum())
    return np.fft.rfftfreq(n, 1.0 / rate), psd


@dataclass(frozen=True)
class ShaperFit:
    kind: str
    freq: float
    vibrations: float      # 0 … 1 of the measured vibration left
    duration_ms: float     # the shaper's length: smoothing / lost sharpness
    score: float


def fit_shapers(freqs: Any, psd: Any, min_freq: float, max_freq: float) -> Tuple[List[ShaperFit], ShaperFit]:
    """Per shaper the best frequency, and the recommendation (lowest score =
    duration × (v^1.5 + 0.2 v + 0.01), Klipper's balance of vibration and
    smoothing)."""
    import numpy as np

    band = (freqs >= min_freq) & (freqs <= max_freq)
    f, p = freqs[band], psd[band]
    total = p.sum()
    if total <= 0:
        raise BadRequestError("no vibration measured — is the accelerometer on the moving part?")
    fits: List[ShaperFit] = []
    for kind in SHAPERS:
        best: Optional[ShaperFit] = None
        for test_freq in np.arange(min_freq, max_freq + 1e-9, FREQ_STEP):
            amps, times = shaper_impulses(kind, float(test_freq))
            ratio = np.max([residual_vibration(amps, times, f, d) for d in TEST_DAMPING], axis=0)
            vibr = float((p * ratio).sum() / total)
            duration = times[-1] * 1000.0
            score = duration * (vibr ** 1.5 + 0.2 * vibr + 0.01)
            if best is None or score < best.score:
                best = ShaperFit(kind, round(float(test_freq), 1), vibr, duration, score)
        assert best is not None
        fits.append(best)
    return fits, min(fits, key=lambda fit: fit.score)


class ResonanceService:
    def __init__(self) -> None:
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.last: dict[str, Any] = {}

    def preload_hal_pins(self) -> None:
        """``webgui.accel-record`` (a CAN node's accelerometer: the HAL
        sampler records while it is on)."""
        from dtos.pins.HalPin import HalDataType
        from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
        from services.Adxl345 import NodeAdxl345, is_node
        from services.HardwareConfigService import HardwareConfigService

        adxl = HardwareConfigService().load_payload().get("adxl345")
        if isinstance(adxl, dict) and is_node(adxl):
            self._record_pin = ReadWriteDynamicHalPin(NodeAdxl345.RECORD_PIN, HalDataType.BIT,
                                                      "Resonance test: record the node accelerometer")
            self._record_pin.set_value(False)

    def _record(self, on: bool) -> None:
        pin = getattr(self, "_record_pin", None)
        if pin is not None:
            pin.set_value(bool(on))

    def accelerometer(self, config: dict[str, Any]) -> Any:
        """The node's (``cs_pin``) or the host's ADXL345."""
        from services.Adxl345 import Adxl345, NodeAdxl345, is_node

        return NodeAdxl345(config, self._record) if is_node(config) else Adxl345(config)

    def is_running(self) -> bool:
        worker = self._worker
        return worker is not None and worker.is_alive()

    @staticmethod
    def _config() -> dict[str, Any]:
        from services.HardwareConfigService import HardwareConfigService

        adxl = HardwareConfigService().load_payload().get("adxl345")
        if not isinstance(adxl, dict):
            raise BadRequestError("No [adxl345] in the profile (an ADXL345 on the host's SPI).")
        return adxl

    def run_command(self, line: str, busy: bool = False) -> bool:
        text = line.split(";", 1)[0].strip()
        head = text.split(None, 1)[0].upper() if text else ""
        if head not in ("SHAPER_CALIBRATE", "TEST_RESONANCES", "ACCELEROMETER_QUERY"):
            return False
        config = self._config()
        if head == "ACCELEROMETER_QUERY":
            self._query(config)
            return True
        params = {k.upper(): v.upper() for k, v in (p.split("=", 1) for p in text.split()[1:] if "=" in p)}
        axis = params.get("AXIS", "").lower()
        if head == "TEST_RESONANCES" and axis not in ("x", "y"):
            raise BadRequestError("TEST_RESONANCES AXIS=X or AXIS=Y.")
        if axis and axis not in ("x", "y"):
            raise BadRequestError(f"{head}: AXIS=X or AXIS=Y.")
        if busy:
            raise ConflictError("A macro, the homing routine or probing is running.")
        self._check_machine()
        with self._lock:
            if self.is_running():
                raise ConflictError(f"{head} is already running.")
            axes = [axis] if axis else ["x", "y"]
            self._worker = threading.Thread(target=self._run_worker, args=(config, axes), name="resonance",
                                            daemon=True)
            self._worker.start()
        return True

    @staticmethod
    def _check_machine() -> None:
        from hardware import get_stat_channel
        from hardware.Connection import MachineState
        from services.ShaperService import get_shaper_service

        if not get_shaper_service().available():
            raise BadRequestError("The test signal needs the jointshape component (a Cartesian Remora machine).")
        stat = get_stat_channel()
        if stat is None:
            raise BadRequestError("LinuxCNC is not running.")
        stat.poll()
        if stat.estop or stat.task_state != MachineState.ON.value:
            raise BadRequestError("Turn the machine on (and out of E-stop) first.")
        homed = list(getattr(stat, "homed", ()) or ())
        if not homed or not all(homed[:2]):
            raise BadRequestError("Home X and Y first.")
        if getattr(stat, "interp_state", 1) != 1:
            raise ConflictError("A program or MDI command is running.")

    def _query(self, config: dict[str, Any]) -> None:
        from services.Adxl345 import Adxl345Error, is_node
        from services.ConsoleLogger import LogLevel, get_console_logger

        chip = self.accelerometer(config)
        try:
            chip.open()
            time.sleep(0.1)
            samples = chip.read_fifo()
        except Adxl345Error as exc:
            raise BadRequestError(f"ACCELEROMETER_QUERY: {exc}") from exc
        finally:
            chip.close()
        if not samples:
            raise BadRequestError("ACCELEROMETER_QUERY: the chip gave no samples.")
        count = len(samples)
        x, y, z = (sum(s[k] for s in samples) / count for k in (1, 2, 3))
        if is_node(config):
            if x == 0.0 and y == 0.0:
                raise BadRequestError("ACCELEROMETER_QUERY: the node sends 0 — the node is lost, its ADXL345 not "
                                      "configured or not found (the hub's boot summary says which).")
            text = f"Accelerometer (node): x {x:.0f}, y {y:.0f} mm/s² ({count} samples)"
        else:
            text = f"Accelerometer: x {x:.0f}, y {y:.0f}, z {z:.0f} mm/s²"
        get_console_logger().log_event(text, level=LogLevel.INFO, source="CMD")

    def _run_worker(self, config: dict[str, Any], axes: List[str]) -> None:
        from services.ConsoleLogger import LogLevel, get_console_logger

        console = get_console_logger()
        try:
            for axis in axes:
                self.measure(config, axis, console.log_event)
        except Exception as exc:  # noqa: BLE001 - report, don't die silently
            logger.exception("resonance test: %s", exc)
            console.log_event(f"Resonance test aborted: {getattr(exc, 'detail', None) or exc}", level=LogLevel.ERROR,
                              source="CMD")

    def measure(self, config: dict[str, Any], axis: str, log: Callable[..., None],
                source: Optional[Callable[[], Any]] = None) -> ShaperFit:
        """Sweep ``axis``, record, fit; ``source`` (tests) replaces the
        accelerometer: a callable returning the samples since the last call."""
        from services.ConsoleLogger import LogLevel
        from services.ShaperService import get_shaper_service

        min_f = float(config.get("min_freq") or 5.0)
        max_f = float(config.get("max_freq") or 133.0)
        rate_hz = float(config.get("hz_per_sec") or 1.0)
        accel_per_hz = float(config.get("accel_per_hz") or 75.0)
        shaper = get_shaper_service()
        chip = None
        if source is None:
            chip = self.accelerometer(config)
            chip.open()
            source = chip.read_fifo
        samples: List[Any] = []
        duration = (max_f - min_f) / rate_hz
        log(f"Resonance test {axis.upper()}: {min_f:g} … {max_f:g} Hz in {duration:.0f} s.", level=LogLevel.INFO,
            source="CMD")
        start = time.monotonic()
        try:
            source()  # drop what was in the FIFO
            while True:
                elapsed = time.monotonic() - start
                freq = min_f + rate_hz * elapsed
                if freq > max_f:
                    break
                shaper.test_signal(axis, accel_per_hz / (4.0 * math.pi * math.pi * freq), freq)
                samples.extend(source())
                time.sleep(0.005)
        finally:
            shaper.stop_test()
            if chip is not None:
                chip.close()
        if chip is not None:
            self._warn_overruns(log)
        column = 1 if axis == "x" else 2
        if len(samples) < 2:
            raise BadRequestError("the accelerometer gave no samples")
        rate = (len(samples) - 1) / max(1e-6, samples[-1][0] - samples[0][0])
        freqs, psd = power_spectrum([s[column] for s in samples], rate)
        fits, best = fit_shapers(freqs, psd, min_f, max_f)
        for fit in fits:
            log(f"  {fit.kind}: {fit.freq:.1f} Hz, vibrations left {fit.vibrations * 100:.1f} %, "
                f"length {fit.duration_ms:.1f} ms", level=LogLevel.DEBUG, source="CMD")
        log(f"Recommended for {axis.upper()}: [input_shaper] shaper_type_{axis}: {best.kind}  "
            f"shaper_freq_{axis}: {best.freq:.1f}  (try it now: SET_INPUT_SHAPER SHAPER_FREQ_{axis.upper()}="
            f"{best.freq:.1f})", level=LogLevel.INFO, source="CMD")
        self.last[axis] = {"fits": [fit.__dict__ for fit in fits], "recommended": best.__dict__,
                           "samples": len(samples), "rate": rate}
        return best


    @staticmethod
    def _warn_overruns(log: Callable[..., None]) -> None:
        """The HAL sampler's FIFO ran over (samples lost): a node only."""
        from hardware.Connection import read_hal_pin
        from services.ConsoleLogger import LogLevel

        try:
            overruns = read_hal_pin("sampler.0.overruns")
        except Exception:  # noqa: BLE001 - a host ADXL has no sampler
            return
        if overruns:
            log(f"The accelerometer recording lost samples ({overruns} overruns): the result may be off.",
                level=LogLevel.WARNING, source="CMD")


_SERVICE: Optional[ResonanceService] = None


def get_resonance_service() -> ResonanceService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = ResonanceService()
    return _SERVICE


__all__ = ["ResonanceService", "ShaperFit", "fit_shapers", "get_resonance_service", "power_spectrum",
           "residual_vibration", "shaper_impulses"]
