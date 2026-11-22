"""Input shaper and skew correction at runtime, and the resonance test
signal — the HAL pins the Remora ``jointshape`` component reads on the X / Y
joints (`JointShapeHalMapper`):

* ``webgui.shaper-freq-x`` / ``-y`` (Hz, 0 = off) — start at the profile's
  ``[input_shaper]``; ``SET_INPUT_SHAPER SHAPER_FREQ_X=<hz> SHAPER_FREQ_Y=<hz>``.
  The component takes a new value over once the axis stands still.
* ``webgui.skew-xy`` — X gets x - factor * y; starts at ``[skew_correction]``;
  ``SET_SKEW XY=<ac>,<bd>,<ad>`` (the calibration print's diagonals and
  side), ``SET_SKEW CLEAR=1``, ``GET_CURRENT_SKEW``.
* ``webgui.resonance-amp-x`` / ``-y`` (mm), ``webgui.resonance-freq`` (Hz):
  the test signal (``ResonanceService``).

Runtime values last until LinuxCNC restarts: put them into the profile.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from core.skew import skew_factor
from dtos.pins.HalPin import HalPin
from dtos.calibration.CalibrationPinsDto import ShaperPins
from mappers.calibration.CalibrationPinsMapper import ShaperMapper
from exceptions import BadRequestError
from services.HalPinService import HalPinService

logger = logging.getLogger("backend.services.shaper")

MAX_SHAPER_FREQ = 300.0
_PARAM = re.compile(r"([A-Za-z_]+)\s*=\s*([^\s]+)")
class ShaperService(HalPinService):
    def __init__(self) -> None:
        self.freq = {"x": 0.0, "y": 0.0}
        self.skew = 0.0
        self._pins: Optional[ShaperPins] = None

    def preload_hal_pins(self) -> None:
        self._pins = ShaperMapper.create_ShaperPins()
        payload = self._payload()
        shaper = payload.get("input_shaper") or {}
        self.freq = {"x": float(shaper.get("freq_x") or 0.0), "y": float(shaper.get("freq_y") or 0.0)}
        self.skew = float((payload.get("skew_correction") or {}).get("xy_factor") or 0.0)

    def apply_initial(self) -> None:
        """Write the start values (after ``HalPin.initialize_component``)."""
        if self._pins is not None:
            for axis in ("x", "y"):
                self._write(self._pins.shaper_freq(axis), self.freq[axis])
            self._write(self._pins.skew_xy, self.skew)
        self.stop_test()

    @staticmethod
    def _payload() -> dict[str, Any]:
        from services.machine.HardwareConfigService import HardwareConfigService

        return HardwareConfigService().load_payload()

    def available(self) -> bool:
        """The machine has the jointshape component on X / Y (Cartesian, or
        CoreXY: there it shapes X / Y before the belt mixing)."""
        payload = self._payload()
        return any(isinstance(payload.get(k), dict) for k in ("input_shaper", "skew_correction", "adxl345"))

    @staticmethod
    def _write(pin: HalPin[float], value: float) -> None:
        pin.set_value(float(value))

    # -- input shaper ------------------------------------------------------- #

    def set_shaper(self, axis: str, freq: float) -> None:
        if not 0.0 <= freq <= MAX_SHAPER_FREQ:
            raise BadRequestError(f"Shaper frequency {freq:g} Hz is outside 0 … {MAX_SHAPER_FREQ:g}.")
        self.freq[axis] = round(float(freq), 2)
        if self._pins is not None:
            self._write(self._pins.shaper_freq(axis), self.freq[axis])

    # -- skew --------------------------------------------------------------- #

    def set_skew(self, factor: float) -> None:
        if abs(factor) > 0.2:
            raise BadRequestError(f"Skew factor {factor:g} is implausibly large (more than 0.2).")
        self.skew = float(factor)
        if self._pins is not None:
            self._write(self._pins.skew_xy, self.skew)

    # -- resonance test ------------------------------------------------------ #

    def test_signal(self, axis: str, amp_mm: float, freq: float) -> None:
        if self._pins is None:
            return
        self._write(self._pins.resonance_freq, freq)
        self._write(self._pins.resonance_amp(axis), amp_mm)
        self._write(self._pins.resonance_amp("y" if axis == "x" else "x"), 0.0)

    def stop_test(self) -> None:
        if self._pins is None:
            return
        self._write(self._pins.resonance_amp_x, 0.0)
        self._write(self._pins.resonance_amp_y, 0.0)
        self._write(self._pins.resonance_freq, 0.0)

    # -- console ------------------------------------------------------------- #

    def run_command(self, line: str) -> bool:
        text = line.split(";", 1)[0].strip()
        head = text.split(None, 1)[0].upper() if text else ""
        if head not in ("SET_INPUT_SHAPER", "SET_SKEW", "GET_CURRENT_SKEW"):
            return False
        if not self.available():
            raise BadRequestError(f"{head}: the profile has no [input_shaper] / [skew_correction] (on a "
                                  "Remora machine, Cartesian or CoreXY) — add one and generate the machine.")
        params = {k.upper(): v for k, v in _PARAM.findall(text[len(head):])}
        if head == "SET_INPUT_SHAPER":
            for axis in ("x", "y"):
                raw = params.get(f"SHAPER_FREQ_{axis.upper()}")
                if raw is not None:
                    self.set_shaper(axis, _number(head, raw))
            message = f"Input shaper: X {self.freq['x']:g} Hz, Y {self.freq['y']:g} Hz"
        elif head == "SET_SKEW":
            if params.get("CLEAR", "0") not in ("0", ""):
                self.set_skew(0.0)
            elif "XY" in params:
                parts = params["XY"].split(",")
                if len(parts) != 3:
                    raise BadRequestError("SET_SKEW XY=<ac>,<bd>,<ad> (the diagonals and a side, mm).")
                try:
                    self.set_skew(skew_factor(*(float(p) for p in parts)))
                except ValueError as exc:
                    raise BadRequestError(f"SET_SKEW: {exc}") from exc
            else:
                raise BadRequestError("SET_SKEW XY=<ac>,<bd>,<ad> or CLEAR=1.")
            message = f"Skew: xy factor {self.skew:.6f} — [skew_correction] xy_skew_factor: {self.skew:.6f}"
        else:
            message = f"Skew: xy factor {self.skew:.6f}"
        from services.machine.ConsoleLogger import LogLevel, get_console_logger

        get_console_logger().log_event(message, level=LogLevel.INFO, source="CMD")
        return True


def _number(command: str, raw: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise BadRequestError(f"{command}: {raw!r} is not a number.") from exc


_SERVICE: Optional[ShaperService] = None


def get_shaper_service() -> ShaperService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = ShaperService()
    return _SERVICE


__all__ = ["ShaperService", "get_shaper_service"]
