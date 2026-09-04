from __future__ import annotations

import logging
from typing import List, Optional, Type, Any, TypeVar

from tools_config_mapper import get_tools
from tools_constants import (
    DEFAULT_SPINDLE_OVERRIDE_PIN,
    G1_EXTRUDE,
    G90_ABSOLUTE,
    G91_RELATIVE,
    M3_FORWARD,
    M4_BACKWARD,
    M5_STOP,
)
from dtos.tools import SpindleDigitalStateDTO, SpindleAnalogStateDTO, HeaterStateDTO, ExtruderStateDTO, ToolPins
from factories.tools.ToolPinTypeFactory import ToolPinTypeFactory
from factories.tools.ToolStateFactory import ToolStateFactory
from factories.tools.ToolHalPinFactory import ToolHalPinFactory

logger = logging.getLogger("backend.tools_service")

T = TypeVar('T', bound=ToolPins)

class ToolsService:

    def __init__(self):
        self._halpins_cache: Optional[List[ToolPins]] = None

    def preload_hal_pins(self) -> None:
        """
        Forces the factory to build the DTOs.
        This queues the pins in HalPin._pending_pins.
        Must be called at startup BEFORE HalPin.initialize_component()
        """
        if self._halpins_cache is not None:
            return

        out: List[ToolPins] = []
        for tool in get_tools():  # Assuming get_tools() reads your JSON config
            pin_map = ToolHalPinFactory.create(tool)
            if pin_map is not None:
                out.append(pin_map)

        self._halpins_cache = out
        logging.info("Preloaded %d tool HAL pin mappings.", len(out))

    def get_halpins(self) -> List[ToolPins]:
        """Returns the pre-built DTOs for your API routes."""
        if self._halpins_cache is None:
            logging.warning("get_halpins() called before preload! Forcing late initialization.")
            self.preload_hal_pins()

        return self._halpins_cache or []

    def get_states(self) -> list[SpindleDigitalStateDTO | SpindleAnalogStateDTO | HeaterStateDTO | ExtruderStateDTO]:
        states = (ToolStateFactory.create(halpin) for halpin in self.get_halpins())
        return [state for state in states if state is not None]

    def get_halpin(self, tool_id: str, expected_type: Type[T]) -> Optional[T]:
        """
        Finds a tool by ID and ensures it matches the requested pin class type.
        """
        for pin_map in self.get_halpins():
            if getattr(pin_map, "id", None) == tool_id:
                extracted_pin = ToolPinTypeFactory.create(pin_map, expected_type)
                if isinstance(extracted_pin, expected_type):
                    return extracted_pin

                logger.warning(
                    "Tool ID '%s' found, but it is a %s, not a %s.",
                    tool_id, type(pin_map).__name__, expected_type.__name__
                )
                return None
        return None

    def get_state(self, tool_id: str, expected_pin_type: Type[T]) -> Any:
        """
        Returns the evaluated DTO state for a specific tool.
        """
        pin_map = self.get_halpin(tool_id, expected_pin_type)
        if pin_map:
            return ToolStateFactory.create(pin_map)
        return None

_tools_service: Optional[ToolsService] = None

def get_tools_service() -> ToolsService:
    """Lazy module-level singleton (tool telemetry / dispatch facade)."""
    global _tools_service
    if _tools_service is None:
        _tools_service = ToolsService()
    return _tools_service

__all__ = [
    "DEFAULT_SPINDLE_OVERRIDE_PIN",
    "G1_EXTRUDE",
    "G90_ABSOLUTE",
    "G91_RELATIVE",
    "M3_FORWARD",
    "M4_BACKWARD",
    "M5_STOP",
    "SpindleDigitalStateDTO",
    "ToolsService",
    "get_tools_service"
]
