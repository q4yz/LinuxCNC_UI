"""Fans, ``[output_pin]`` outputs and ``[input_pin]`` inputs for the UI
(`.agent/component/io_pins.md`).

Every one is a ``webgui.<id>`` pin netted in ``webgui_connections.hal``:

* a part fan: float, 0 ... 100 % into ``remora.SP.N`` (``FansService``
  owns the pin — a heater-derived fan is left to its heater);
* a switched output: bit; a PWM output: float in its ``scale`` units
  (HAL scales it to %);
* an input: bit, read only.

An output an ``[input_pin]`` sets (``*_halpin_set``) is latched in HAL
(``OutputLatchHalMapper``): the UI is one event of it — write the value
to ``webgui.<id>`` (float), then toggle ``webgui.<id>-set`` — and the
latched result comes back on ``webgui.<id>-state``.

Outputs start at their profile ``value`` once the component is up
(``apply_start_values``).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from dtos.pins.HalPin import HalDataType, HalPin
from dtos.pins.ReadOnlyDynamicHalPin import ReadOnlyDynamicHalPin
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from exceptions import BadRequestError, NotFoundError
from models.IoModels import IoFan, IoInput, IoOutput, IoState
from services.FansService import get_fans_service
from services.HardwareConfigService import HardwareConfigService

logger = logging.getLogger("backend.services.io")

FAN_MAX = 100.0


class _Latch:
    """The UI's pins into a latched output (see module doc)."""

    def __init__(self, pin_id: str) -> None:
        self.set = ReadWriteDynamicHalPin(f"{pin_id}-set", HalDataType.BIT, f"Output pin {pin_id}: apply")
        self.state = ReadOnlyDynamicHalPin(f"{pin_id}-state", HalDataType.FLOAT, f"Output pin {pin_id}: value")


class IoService:
    def __init__(self) -> None:
        self._outputs: Dict[str, tuple[Dict[str, Any], HalPin[Any]]] = {}
        self._latches: Dict[str, _Latch] = {}
        self._inputs: Dict[str, HalPin[bool]] = {}
        self._preloaded = False

    def preload_hal_pins(self, payload: Optional[Dict[str, Any]] = None) -> None:
        """Queue the output / input pins. Call before ``HalPin.initialize_component()``."""
        if self._preloaded:
            return
        payload = payload if payload is not None else HardwareConfigService().load_payload()
        latched = {
            str(entry.get("output"))
            for inp in payload.get("input_pins") or []
            for edge in ("rising", "falling")
            for entry in inp.get(f"{edge}_halpin_set") or []
        }
        for out in payload.get("output_pins") or []:
            pin_id = str(out["id"])
            # a latch stage takes a float, a direct switch a bit
            hal_type = HalDataType.FLOAT if out.get("pwm") or pin_id in latched else HalDataType.BIT
            pin: HalPin[Any] = ReadWriteDynamicHalPin(pin_id, hal_type, f"Output pin {pin_id}")
            self._outputs[pin_id] = (out, pin)
            if pin_id in latched:
                self._latches[pin_id] = _Latch(pin_id)
        for inp in payload.get("input_pins") or []:
            pin_id = str(inp["id"])
            self._inputs[pin_id] = ReadOnlyDynamicHalPin(pin_id, HalDataType.BIT, f"Input pin {pin_id}")
        self._preloaded = True
        logger.info("Preloaded %d output and %d input pins.", len(self._outputs), len(self._inputs))

    def apply_start_values(self) -> None:
        """Each output's profile ``value`` — after ``HalPin.initialize_component()``."""
        for pin_id, (out, _pin) in self._outputs.items():
            try:
                self._write(pin_id, float(out.get("value") or 0.0))
            except Exception as exc:  # a missing HAL must not stop the backend
                logger.warning("Output %s: start value not set: %s", pin_id, exc)

    # -- queries ---------------------------------------------------------- #

    def state(self) -> IoState:
        fans = [
            IoFan(id=fan.id, value=float(fan.speed.get_value() or 0.0))
            for fan in get_fans_service().get_halpins()
        ]
        outputs = [
            IoOutput(
                id=pin_id,
                pwm=bool(out.get("pwm")),
                scale=float(out.get("scale") or 1.0),
                value=self._read(pin_id),
            )
            for pin_id, (out, _pin) in self._outputs.items()
        ]
        inputs = [IoInput(id=pin_id, value=bool(pin.get_value())) for pin_id, pin in self._inputs.items()]
        return IoState(fans=fans, outputs=outputs, inputs=inputs)

    # -- commands --------------------------------------------------------- #

    def set_value(self, pin_id: str, value: float) -> IoState:
        """A fan in % (0 ... 100), a PWM output in its ``scale`` units, a
        switched output 0 / anything else = on."""
        fan = next((f for f in get_fans_service().get_halpins() if f.id == pin_id), None)
        if fan is not None:
            fan.speed.set_value(min(FAN_MAX, max(0.0, float(value))))
            return self.state()
        if pin_id in self._outputs:
            self._write(pin_id, value)
            return self.state()
        if pin_id in self._inputs:
            raise BadRequestError(f"{pin_id!r} is an input; it cannot be set.")
        raise NotFoundError(f"No fan or output pin named {pin_id!r}.")

    def _write(self, pin_id: str, value: float) -> None:
        out, pin = self._outputs[pin_id]
        latch = self._latches.get(pin_id)
        if latch is None:
            pin.set_value(self._hal_value(out, value))
            return
        # a latch stage is a float; toggling -set makes it one event
        pin.set_value(float(self._hal_value(out, value)))
        latch.set.set_value(not latch.set.get_value())

    def _read(self, pin_id: str) -> float:
        latch = self._latches.get(pin_id)
        pin = latch.state if latch is not None else self._outputs[pin_id][1]
        return float(pin.get_value() or 0.0)

    @staticmethod
    def _hal_value(out: Dict[str, Any], value: float) -> Any:
        if out.get("pwm"):
            return min(float(out.get("scale") or 1.0), max(0.0, float(value)))
        return bool(value)


_service: Optional[IoService] = None


def get_io_service() -> IoService:
    global _service
    if _service is None:
        _service = IoService()
    return _service


__all__ = ["IoService", "get_io_service"]
