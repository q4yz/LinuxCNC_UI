from typing import Union, Dict, Optional

from pydantic import BaseModel, Field

from models.axis_model import AxisStateResponse
from services.ProgramService import ProgramProgressResponse
from models.temperature_response import TemperatureStateResponse
from factories.tools.ToolResponseFactory import ToolStateResponseModel
from models.tools.HeaterModels import HeaterStateResponse


class BaseThreadSnapshotResponse(BaseModel):
    """Flat snapshot of every slow stream the dashboard polls at 1 Hz.

    All sub-snapshot fields are ``Optional[...] = None`` so that
    ``response_model_exclude_none=True`` on the route can drop the
    fields the caller didn't ask for (see ``?mode=`` in
    :mod:`routers.base_thread`). ``timestamp`` is always populated
    — it identifies the snapshot itself, not a sub-stream.
    """

    progress: Optional[ProgramProgressResponse] = Field(
        None,
        description="Active program progress..."
    )
    sensors: Optional[Dict[str, Union['HeaterStateResponse', 'TemperatureStateResponse']]] = Field(
        default=None,
        description="Temperature sensors keyed by ID..."
    )
    tools: Optional[Dict[str, 'ToolStateResponseModel']] = Field(
        default=None,
        description="Operator-facing tool list..."
    )
    timestamp: Optional[str] = Field(
        None,
        description="ISO-8601 timestamp..."
    )
    axis: Optional[Dict[str, 'AxisStateResponse']] = Field(
        default=None,
        description=(
            "Static axis information keyed by canonical LinuxCNC letter "
            "id ('x', 'y', 'z', 'a', ...). Each entry lists the "
            "joint_numbers of every motor driving that axis."
        )
    )
