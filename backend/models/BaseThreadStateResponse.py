from typing import Union, Dict, Optional

from pydantic import BaseModel, Field

from modules.axis.models.axis_model import AxisStateResponse
from modules.program.service import ProgramProgressResponse
from modules.temperature.models.temperature_models import TemperatureStateResponse
from modules.tools.factory.tool_response_factory import ToolStateResponseModel
from modules.tools.models.heater_models import HeaterStateResponse


class BaseThreadSnapshotResponse(BaseModel):
    """Flat snapshot of every slow stream the dashboard polls at 1 Hz."""

    progress: Optional[ProgramProgressResponse] = Field(
        None,
        description="Active program progress..."
    )
    sensors: Optional[Dict[str, Union['HeaterStateResponse', 'TemperatureStateResponse']]] = Field(
        default_factory=dict, # An empty dict is often better than None for collections
        description="Temperature sensors keyed by ID..."
    )
    tools: Optional[Dict[str, 'ToolStateResponseModel']] = Field(
        default_factory=dict,
        description="Operator-facing tool list..."
    )
    timestamp: Optional[str] = Field(
        None,
        description="ISO-8601 timestamp..."
    )
    axis: Optional[Dict[str, 'AxisStateResponse']] = Field(
        default_factory=dict,
        description="Static axis information"
    )
