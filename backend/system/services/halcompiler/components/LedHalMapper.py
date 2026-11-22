"""``[neopixel NAME]`` -> a set point per colour segment
(`.agent/component/neopixel.md` § 3).

Each segment's colour is one float, 0xRRGGBB, from the machine backend
(``webgui.led-<id>-<k>``) to a Remora set point; the Remora router turns
a chain's segments into one firmware "RGB" module (Remora-m8p
``modules/rgb``: WS2812 / SK6812 on a timer channel + DMA, on the hub or
a CAN node).
"""
from __future__ import annotations

from mappers.machineconfig import PinStringMapper
from models.machineconfig.HardwareJsonModels import Led
from models.machineconfig.HalFragmentModels import HalFragment, PinRequest, PinRole


class LedHalMapper:
    @staticmethod
    def segment_signal(led_id: str, index: int) -> str:
        return f"{led_id}-rgb{index}"

    @staticmethod
    def segment_pin(led_id: str, index: int) -> str:
        """The machine backend's pin (``webgui.<this>``) for one segment."""
        return f"led-{led_id}-{index}"

    @staticmethod
    def segments(led: Led) -> list[list[int]]:
        """``[first, count]`` per colour channel; no segments: the whole chain."""
        return led.segments or [[1, led.chain_count]]

    @staticmethod
    def to_fragment(led: Led) -> HalFragment:
        fragment = HalFragment()
        pin = PinStringMapper.from_string(led.pin)
        for k, (first, count) in enumerate(LedHalMapper.segments(led)):
            fragment.requests.append(
                PinRequest(
                    signal=LedHalMapper.segment_signal(led.id, k),
                    role=PinRole.RGB,
                    pin=pin,
                    owner=led.id,
                    led=(led.chain_count, led.color_order, int(first), int(count)),
                )
            )
        return fragment


__all__ = ["LedHalMapper"]
