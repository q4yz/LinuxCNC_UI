from dataclasses import dataclass
from typing import Any

from dtos.pins.HalPin import HalPin, HalDirection


@dataclass(frozen=True, slots=True)
class UnconnectedHalPin(HalPin[Any]):
    """Represents a pin that is intentionally left blank."""


    def get_value(self) -> None:
        return None

    def get_doc_string(self) -> str:
        return f"None-Unconnected-Dummy-Pin : Should be overridden by real pins"

    def get_direction(self) -> HalDirection:
        return None

    def get_pin_name(self) -> str:
        return "unconnected"
