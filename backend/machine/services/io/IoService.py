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
(``apply_initial``).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from dtos.io.IoDto import IoOutputPins, IoPins, IoStateDTO
from exceptions import BadRequestError, NotFoundError
from mappers.io.IoMapper import IoMapper
from services.HalPinService import HalPinService
from services.io.FansService import get_fans_service
from services.machine.HardwareConfigService import HardwareConfigService

logger = logging.getLogger("backend.services.io")

FAN_MAX = 100.0


class IoService(HalPinService):
    def __init__(self) -> None:
        self._pins = IoPins()
        self._preloaded = False

    def preload_hal_pins(self) -> None:
        """Queue the output / input pins. Call before ``HalPin.initialize_component()``."""
        if self._preloaded:
            return
        self._pins = IoMapper.from_dict_to_IoPins(HardwareConfigService().load_payload())
        self._preloaded = True
        logger.info("Preloaded %d output and %d input pins.", len(self._pins.outputs), len(self._pins.inputs))

    def apply_initial(self) -> None:
        """Each output's profile ``value`` — after ``HalPin.initialize_component()``."""
        for out in self._pins.outputs:
            try:
                self._write(out, out.start_value)
            except Exception as exc:  # a missing HAL must not stop the backend
                logger.warning("Output %s: start value not set: %s", out.id, exc)

    # -- queries ---------------------------------------------------------- #

    def input_value(self, pin_id: str) -> bool | None:
        """An ``[input_pin]``'s reading (``None``: no such input, or unreadable)."""
        pin = next((i for i in self._pins.inputs if i.id == pin_id), None)
        if pin is None:
            return None
        try:
            value = pin.pin.get_value()
        except Exception:  # noqa: BLE001 - HAL gone
            return None
        return None if value is None else bool(value)

    def state(self) -> IoStateDTO:
        return IoMapper.to_state_dto(self._pins, get_fans_service().get_halpins())

    # -- commands --------------------------------------------------------- #

    def set_value(self, pin_id: str, value: float) -> IoStateDTO:
        """A fan in % (0 ... 100), a PWM output in its ``scale`` units, a
        switched output 0 / anything else = on."""
        fan = next((f for f in get_fans_service().get_halpins() if f.id == pin_id), None)
        if fan is not None:
            fan.speed.set_value(min(FAN_MAX, max(0.0, float(value))))
            return self.state()
        out = next((o for o in self._pins.outputs if o.id == pin_id), None)
        if out is not None:
            self._write(out, value)
            return self.state()
        if any(i.id == pin_id for i in self._pins.inputs):
            raise BadRequestError(f"{pin_id!r} is an input; it cannot be set.")
        raise NotFoundError(f"No fan or output pin named {pin_id!r}.")

    @staticmethod
    def _write(out: IoOutputPins, value: float) -> None:
        if out.latch_set is None:
            out.pin.set_value(IoService._hal_value(out, value))
            return
        # a latch stage is a float; toggling -set makes it one event
        out.pin.set_value(float(IoService._hal_value(out, value)))
        out.latch_set.set_value(not out.latch_set.get_value())

    @staticmethod
    def _hal_value(out: IoOutputPins, value: float) -> Any:
        if out.pwm:
            return min(out.scale, max(0.0, float(value)))
        return bool(value)


_service: Optional[IoService] = None


def get_io_service() -> IoService:
    global _service
    if _service is None:
        _service = IoService()
    return _service


__all__ = ["IoService", "get_io_service"]
