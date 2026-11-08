"""WS2812 / SK6812 LED chains (`.agent/component/neopixel.md` § 4).

One ``webgui.led-<id>-<k>`` float per colour segment (0xRRGGBB), wired to
a Remora set point by the generated HAL. Set from the UI
(``/api/v1/leds``), Klipper's ``SET_LED`` (MDI, ``.macro`` lines) and the
``M183`` helper (uploaded prints: ``SET_LED`` / Marlin ``M150``). A
Klipper ``INDEX`` sets the segment that LED belongs to.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.led_color import SetLed, decode, encode, parse_set_led
from dtos.pins.HalPin import HalDataType
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from exceptions import BadRequestError, NotFoundError
from services.HardwareConfigService import HardwareConfigService

logger = logging.getLogger("backend.services.LedService")


class LedService:
    def __init__(self, config: Optional[HardwareConfigService] = None) -> None:
        self._config = config or HardwareConfigService()
        self._leds: List[Dict[str, Any]] = []
        self._pins: Dict[str, List[ReadWriteDynamicHalPin[float]]] = {}

    def preload_hal_pins(self) -> None:
        """One pin per segment. Call before ``HalPin.initialize_component()``."""
        if self._pins:
            return
        self._leds = [led for led in self._config.load_payload().get("leds") or [] if isinstance(led, dict)]
        for led in self._leds:
            led_id = str(led["id"])
            self._pins[led_id] = [
                ReadWriteDynamicHalPin[float](f"led-{led_id}-{k}", HalDataType.FLOAT, f"LED {led_id} segment {k + 1}: 0xRRGGBB")
                for k in range(len(self._segments(led)))
            ]

    def apply_initial(self) -> None:
        """The ``initial_*`` colours, once the pins exist."""
        for led in self._leds:
            red, green, blue, white = (list(led.get("initial") or []) + [0.0] * 4)[:4]
            if red or green or blue or white:
                self.set(SetLed(led=str(led["id"]), red=red, green=green, blue=blue, white=white))

    @staticmethod
    def _segments(led: Dict[str, Any]) -> List[List[int]]:
        return [list(s) for s in led.get("segments") or [[1, int(led.get("chain_count") or 1)]]]

    def _led(self, led_id: str) -> Dict[str, Any]:
        led = next((l for l in self._leds if str(l["id"]) == led_id), None)
        if led is None:
            raise NotFoundError(f"No LED named {led_id!r}.")
        return led

    def state(self) -> List[Dict[str, Any]]:
        out = []
        for led in self._leds:
            led_id = str(led["id"])
            segments = []
            for (first, count), pin in zip(self._segments(led), self._pins.get(led_id, [])):
                red, green, blue = decode(float(pin.get_value() or 0.0))
                segments.append({"first": first, "count": count, "red": red, "green": green, "blue": blue})
            out.append({
                "id": led_id, "chain_count": int(led.get("chain_count") or 1),
                "color_order": str(led.get("color_order") or "GRB"), "segments": segments,
            })
        return out

    def set(self, command: SetLed) -> List[Dict[str, Any]]:
        """Set a chain (``index`` None) or the segment holding LED ``index``."""
        led = self._led(command.led)
        segments = self._segments(led)
        targets = list(range(len(segments)))
        if command.index is not None:
            targets = [k for k, (first, count) in enumerate(segments) if first <= command.index < first + count]
            if not targets:
                raise BadRequestError(
                    f"LED {command.led!r} has LEDs 1 ... {int(led.get('chain_count') or 1)}, not {command.index}."
                )
        color = float(encode(command.red, command.green, command.blue, command.white))
        for k in targets:
            self._pins[command.led][k].set_value(color)
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
