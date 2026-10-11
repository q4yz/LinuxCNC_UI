"""Mock waveforms for the dev HAL pin list (debug tab / oscilloscope).

Without real HAL the debug pin list is ``HalPinSignalService._mock_pins``
and every unknown ``hal.get_value`` returns the mock's 0.0 default — so
the oscilloscope would only ever draw flat lines in dev. This component
answers those pin names with time-based signals (sine, square, triangle,
pulses, a lagging follower) so trigger, scaling and multi-channel display
can be developed and checked without a machine.

Read-only: it never claims writes (``set_pin`` returns ``False``).
"""
from __future__ import annotations

import math
import time
from typing import Any, Callable, Dict, Optional

from hardware.mock.tools.MockComponent import MockComponent


def _square(t: float, hz: float, duty: float = 0.5) -> bool:
    return (t * hz) % 1.0 < duty


def _triangle(t: float, hz: float) -> float:
    phase = (t * hz) % 1.0
    return 1.0 - abs(2.0 * phase - 1.0)


_SIGNALS: Dict[str, Callable[[float], Any]] = {
    "axis.x-pos-cmd": lambda t: 50.0 * math.sin(2 * math.pi * 0.5 * t),
    # The "drive feedback" lags the command by 40 ms.
    "spindle.x-pos-fb": lambda t: 50.0 * math.sin(2 * math.pi * 0.5 * (t - 0.04)),
    "motion.spindle-on": lambda t: _square(t, 1.0),
    "motion.spindle-speed-out": lambda t: 1200.0 + 300.0 * math.sin(2 * math.pi * 0.2 * t),
    "motion.feed-cmd": lambda t: 1000.0 * _triangle(t, 0.25),
    "motion.coolant-mist": lambda t: _square(t, 5.0, duty=0.2),
    "spindle.at-speed": lambda t: _square(t + 0.25, 0.5),
    "motion.spindle-at-speed": lambda t: _square(t + 0.25, 0.5),
}


class MockDebugSignals(MockComponent):
    COMPONENT_ID = "debug-signals"

    def __init__(self) -> None:
        self.id = self.COMPONENT_ID
        self._t0 = time.monotonic()

    def read_pin(self, pin_name: str) -> Optional[Any]:
        signal = _SIGNALS.get(pin_name)
        return None if signal is None else signal(time.monotonic() - self._t0)

    def set_pin(self, pin_name: str, value: Any) -> bool:
        return False

    def update(self, hal, nml, delta_time: float) -> None:
        return None

    def execute_mdi(self, gcode: str) -> bool:
        return False


__all__ = ["MockDebugSignals"]
