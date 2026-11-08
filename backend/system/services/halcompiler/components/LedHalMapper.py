"""``[neopixel NAME]`` -> a set point per colour segment
(`.agent/component/neopixel.md` § 3).

Each segment's colour is one float, 0xRRGGBB, from the machine backend
(``webgui.led-<id>-<k>``) to a Remora set point; the Remora router turns
a chain's segments into one firmware "RGB" module (Remora-m8p
``modules/rgb``: WS2812 / SK6812 on a timer channel + DMA, on the hub or
a CAN node).
"""
from __future__ import annotations

from typing import Any

from mappers.machineconfig import PinStringMapper
from models.machineconfig.HalFragmentModels import HalFragment, PinRequest, PinRole


def segment_signal(led_id: str, index: int) -> str:
    return f"{led_id}-rgb{index}"


def segment_pin(led_id: str, index: int) -> str:
    """The machine backend's pin (``webgui.<this>``) for one segment."""
    return f"led-{led_id}-{index}"


class LedHalMapper:
    @staticmethod
    def to_fragment(led: dict[str, Any]) -> HalFragment:
        fragment = HalFragment()
        led_id = str(led["id"])
        pin = PinStringMapper.from_string(str(led["pin"]))
        for k, (first, count) in enumerate(led.get("segments") or [[1, int(led.get("chain_count") or 1)]]):
            fragment.requests.append(
                PinRequest(
                    signal=segment_signal(led_id, k),
                    role=PinRole.RGB,
                    pin=pin,
                    owner=led_id,
                    led=(int(led.get("chain_count") or 1), str(led.get("color_order") or "GRB"), int(first), int(count)),
                )
            )
        return fragment


class LedWebguiMapper:
    @staticmethod
    def to_lines(led: dict[str, Any]) -> list[str]:
        led_id = str(led["id"])
        lines = [f"# LED: {led_id}"]
        for k in range(len(led.get("segments") or [[1, 1]])):
            lines.append(f"net {segment_signal(led_id, k)} <= webgui.{segment_pin(led_id, k)}")
        return lines + [""]


__all__ = ["LedHalMapper", "LedWebguiMapper", "segment_pin", "segment_signal"]
