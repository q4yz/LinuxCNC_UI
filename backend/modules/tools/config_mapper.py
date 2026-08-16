from __future__ import annotations

import logging
from typing import Any, Dict, List

from services.hardware_config_service import HardwareConfigService


from modules.tools.constants import ToolType

logger = logging.getLogger("backend.modules.tools.tools_loader")


def get_tools() -> List[Dict[str, Any]]:
    config_service = HardwareConfigService()
    tools_list = config_service.get_tools()

    out: List[Dict[str, Any]] = []
    for entry in tools_list:
        if not isinstance(entry, dict):
            continue
        if not isinstance(entry.get("id"), str) or not entry["id"]:
            continue
        out.append(entry)
    return out

def get_tool(tool_id: str) -> Dict[str, Any]:
    return _get_tool(tool_id, get_tools())

def get_tool_type(tool_type: ToolType) -> List[Dict[str, Any]]:
    target_type = tool_type.value if isinstance(tool_type, ToolType) else tool_type
    return [tool for tool in get_tools()if tool.get("type") == target_type]

def get_digital_spindle(tool_id: str)-> Dict[str, Any]:
    return _get_tool(tool_id, get_tool_type(ToolType.SPINDLE_DIGITAL))

def get_analog_spindle(tool_id: str)-> Dict[str, Any]:
    return _get_tool(tool_id, get_tool_type(ToolType.SPINDLE_ANALOG))

def get_extruder(tool_id: str)-> Dict[str, Any]:
    return _get_tool(tool_id, get_tool_type(ToolType.EXTRUDER))

def get_heater(tool_id: str) -> Dict[str, Any]:
    return _get_tool(tool_id, get_tool_type(ToolType.HEATED_BED))

def get_all_heater()-> List[Dict[str, Any]]:
    return get_tool_type(ToolType.EXTRUDER) + get_tool_type(ToolType.HEATED_BED)

def _get_tool(tool_id: str, list: List[Dict[str, Any]]) -> Dict[str, Any]:
    for tool in list:
        if tool.get("id") == tool_id:
            return tool
    raise KeyError( f"Tool ID '{tool_id}' not found in the active hardware configuration." )
