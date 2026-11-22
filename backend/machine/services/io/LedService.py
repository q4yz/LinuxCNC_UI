"""WS2812 / SK6812 LED chains (`.agent/component/neopixel.md` § 4).

One ``webgui.led-<id>-<k>`` float per colour segment (0xRRGGBB), wired to
a Remora set point by the generated HAL. Set from the UI
(``/api/v1/leds``), Klipper's ``SET_LED`` (MDI, ``.macro`` lines) and the
``M183`` helper (uploaded prints: ``SET_LED`` / Marlin ``M150``). A
Klipper ``INDEX`` sets the segment that LED belongs to.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from core.led_color import SetLed, encode, parse_set_led
from dtos.leds.LedDto import LedPins, LedStateDTO
from exceptions import BadRequestError, NotFoundError
from mappers.leds.LedMapper import LedMapper
from services.HalPinService import HalPinService
from services.machine.HardwareConfigService import HardwareConfigService

logger = logging.getLogger("backend.services.io.LedService")


class LedService(HalPinService):
    def __init__(self, config: Optional[HardwareConfigService] = None) -> None:
        self._config = config or HardwareConfigService()
        self._leds: tuple[LedPins, ...] = ()

    def preload_hal_pins(self) -> None:
        """One pin per segment. Call before ``HalPin.initialize_component()``."""
        if self._leds:
            return
        self._leds = tuple(
            LedMapper.from_dict_to_LedPins(led)
            for led in self._config.load_payload().get("leds") or [] if isinstance(led, dict)
        )

    def apply_initial(self) -> None:
        """The ``initial_*`` colours, once the pins exist."""
        for led in self._leds:
            red, green, blue, white = led.initial
            if red or green or blue or white:
                self.set(SetLed(led=led.id, red=red, green=green, blue=blue, white=white))

    def _led(self, led_id: str) -> LedPins:
        led = next((l for l in self._leds if l.id == led_id), None)
        if led is None:
            raise NotFoundError(f"No LED named {led_id!r}.")
        return led

    def state(self) -> List[LedStateDTO]:
        return [LedMapper.to_state_dto(led) for led in self._leds]

    def set(self, command: SetLed) -> List[LedStateDTO]:
        """Set a chain (``index`` None) or the segment holding LED ``index``."""
        led = self._led(command.led)
        targets = list(range(len(led.segments)))
        if command.index is not None:
            targets = [k for k, (first, count) in enumerate(led.segments) if first <= command.index < first + count]
            if not targets:
                raise BadRequestError(f"LED {command.led!r} has LEDs 1 ... {led.chain_count}, not {command.index}.")
        color = float(encode(command.red, command.green, command.blue, command.white))
        for k in targets:
            led.pins[k].set_value(color)
        return self.state()
    def run_command(self, line: str) -> bool:
        """A ``SET_LED`` line (MDI, macro): set it and ``True``; ``False``
        for any other line. Raises ``BadRequestError`` for a bad one."""
        try:
            command = parse_set_led(line)
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc
        if command is None:
            return False
        self.set(command)
        return True


_SERVICE: Optional[LedService] = None


def get_led_service() -> LedService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = LedService()
    return _SERVICE


__all__ = ["LedService", "get_led_service"]
