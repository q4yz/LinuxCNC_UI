from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from modules.tools.config_mapper import get_tools
from modules.tools.constants import (
    DEFAULT_SPINDLE_OVERRIDE_PIN,
    G1_EXTRUDE,
    G90_ABSOLUTE,
    G91_RELATIVE,
    M3_FORWARD,
    M4_BACKWARD,
    M5_STOP,
)
from modules.tools.dtos.digital_spindle_dto import SpindleDigitalStateDTO
from modules.tools.factory.tool_state_factory import ToolStateFactory
from modules.tools.factory.tool_halpin_factory import ToolHalPinFactory

logger = logging.getLogger("backend.modules.tools.service")

class ToolsService:

    def get_halpins(self) -> list:
        out = []
        for tool in get_tools():
            pin_map = ToolHalPinFactory.create(tool)
            if pin_map is not None:
                out.append(pin_map)
        return out

    def get_states(self) -> List[Dict[str, Any]]:
        return [ToolStateFactory.create(halpin) for halpin in self.get_halpins()]

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
    "get_tools_service",

]
