"""HAL pin values for the debug tab: a cheap 1 Hz read of chosen pins and
the oscilloscope's fast sampler.

Both read pins in-process with ``hal.get_value`` (microseconds per pin)
through :func:`hardware.read_hal_pin` — not ``halcmd show pin``, which
forks a process and lists every pin.

**Sampler.** One background thread per oscilloscope connection samples
its pins at ``rate_hz`` and hands blocks of samples (every ``BLOCK_S``)
to the connection via ``emit``. Every sample carries the time it was
actually taken (``time.perf_counter`` since the sampler started), so a
late sample (Python is not realtime; LinuxCNC's servo thread is) shows
up as a gap, never as a wrong waveform. The thread never touches the
event loop itself — ``emit`` is responsible for that.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from exceptions import BadRequestError
from hardware.Connection import read_hal_pin

logger = logging.getLogger("backend.services.HalScopeService")

MAX_SCOPE_PINS = 16
MIN_RATE_HZ = 10
MAX_RATE_HZ = 1000
DEFAULT_RATE_HZ = 200
#: Samples are sent in blocks this long (≈20 frames/s regardless of rate).
BLOCK_S = 0.05
#: Upper bound for the 1 Hz value read (whole visible pin list).
MAX_VALUE_PINS = 2000

_PIN_NAME = re.compile(r"^[A-Za-z0-9_.\-]+$")

Emit = Callable[[Dict[str, Any]], None]
Reader = Callable[[str], Any]


def scope_value(raw: Any) -> Optional[float]:
    """A pin value as a plottable number: bit → 0/1, numbers as-is, anything
    unreadable → ``None`` (a gap in the trace)."""
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _validate_pins(pins: Any, limit: int) -> List[str]:
    if not isinstance(pins, list) or not pins:
        raise BadRequestError("pins must be a non-empty list of HAL pin names")
    if len(pins) > limit:
        raise BadRequestError(f"at most {limit} pins")
    bad = [p for p in pins if not isinstance(p, str) or not _PIN_NAME.match(p)]
    if bad:
        raise BadRequestError(f"invalid HAL pin name(s): {bad[:5]}")
    return list(dict.fromkeys(pins))  # de-duplicated, order kept


class ScopeSampler:
    """Samples ``pins`` at ``rate_hz`` in its own thread until :meth:`stop`."""

    def __init__(
        self,
        pins: Sequence[str],
        rate_hz: float,
        emit: Emit,
        read: Reader = read_hal_pin,
    ) -> None:
        self.pins = list(pins)
        self.rate_hz = rate_hz
        self._emit = emit
        self._read = read
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="hal-scope-sampler", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout)

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def _sample(self) -> List[Optional[float]]:
        values: List[Optional[float]] = []
        for pin in self.pins:
            try:
                values.append(scope_value(self._read(pin)))
            except Exception:  # noqa: BLE001 - one bad pin is a gap, not a dead scope
                values.append(None)
        return values

    def _flush(self, times: List[float], columns: List[List[Optional[float]]], missed: int) -> None:
        self._emit({
            "type": "samples",
            "pins": self.pins,
            "t": times,
            "v": columns,
            "missed": missed,
        })

    def _run(self) -> None:
        period = 1.0 / self.rate_hz
        start = time.perf_counter()
        next_at = start
        last_flush = start
        times: List[float] = []
        columns: List[List[Optional[float]]] = [[] for _ in self.pins]
        missed = 0
        try:
            while not self._stop.is_set():
                now = time.perf_counter()
                if now < next_at:
                    self._stop.wait(next_at - now)
                    continue
                times.append(round(now - start, 6))
                for column, value in zip(columns, self._sample()):
                    column.append(value)
                next_at += period
                if next_at < now - period:
                    # Fell behind (busy CPU): skip instead of bursting.
                    skipped = int((now - next_at) / period)
                    missed += skipped
                    next_at += skipped * period
                if now - last_flush >= BLOCK_S:
                    self._flush(times, columns, missed)
                    times, columns, missed = [], [[] for _ in self.pins], 0
                    last_flush = now
        except Exception:  # noqa: BLE001 - report, never die silently
            logger.exception("HAL scope sampler crashed")
            self._emit({"type": "error", "message": "sampler stopped (see machine backend log)"})


class HalScopeService:
    def __init__(self, read: Reader = read_hal_pin) -> None:
        self._read = read
        self._samplers: List[ScopeSampler] = []
        self._lock = threading.Lock()

    def read_values(self, pins: Any) -> Dict[str, Any]:
        """Current value of each pin (``None`` when unreadable) — the debug
        tab's 1 Hz poll of the pins on screen."""
        names = _validate_pins(pins, MAX_VALUE_PINS)
        values: Dict[str, Any] = {}
        for name in names:
            try:
                raw = self._read(name)
            except Exception:  # noqa: BLE001
                raw = None
            values[name] = raw if isinstance(raw, (bool, int, float)) else None
        return values

    def start_sampler(self, pins: Any, rate_hz: Any, emit: Emit) -> ScopeSampler:
        names = _validate_pins(pins, MAX_SCOPE_PINS)
        try:
            rate = float(rate_hz) if rate_hz is not None else DEFAULT_RATE_HZ
        except (TypeError, ValueError) as exc:
            raise BadRequestError("rate_hz must be a number") from exc
        rate = min(max(rate, MIN_RATE_HZ), MAX_RATE_HZ)
        sampler = ScopeSampler(names, rate, emit, self._read)
        with self._lock:
            self._samplers = [s for s in self._samplers if s.running]
            self._samplers.append(sampler)
        sampler.start()
        logger.info("HAL scope sampling %d pin(s) at %.0f Hz", len(names), rate)
        return sampler

    def stop_all(self) -> None:
        """Shutdown: stop every sampler (they are daemon threads, but HAL
        must not be read while the component is being removed)."""
        with self._lock:
            samplers, self._samplers = self._samplers, []
        for sampler in samplers:
            sampler.stop()


_SERVICE_INSTANCE: Optional[HalScopeService] = None


def get_hal_scope_service() -> HalScopeService:
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = HalScopeService()
    return _SERVICE_INSTANCE


__all__ = [
    "BLOCK_S",
    "DEFAULT_RATE_HZ",
    "HalScopeService",
    "MAX_RATE_HZ",
    "MAX_SCOPE_PINS",
    "MIN_RATE_HZ",
    "ScopeSampler",
    "get_hal_scope_service",
    "scope_value",
]
