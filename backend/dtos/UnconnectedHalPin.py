from dataclasses import dataclass
from typing import Any

from dtos.HalPin import HalPin


@dataclass(frozen=True, slots=True)
class UnconnectedHalPin(HalPin[Any]):
    """Represents a pin that is intentionally left blank."""

    def is_static(self) -> bool:
        return True

    def get_value(self) -> None:
        return None
