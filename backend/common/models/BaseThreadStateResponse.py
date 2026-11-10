from typing import Union, Dict, List, Optional

from pydantic import BaseModel, Field

from models.AxisModels import AxisStateResponse, SpeedOverrideResponse
from models.IoModels import IoState
from models.LedModels import Led
from models.McuModels import McuStateResponse
from models.program.ProgramModels import ProgramProgressResponse
from models.TemperatureStateResponse import TemperatureStateResponse
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
    speed_override: Optional['SpeedOverrideResponse'] = Field(
        default=None,
        description=(
            "Live feed override (fraction, 1.0 = 100 %) and absolute speed cap "
            "(mm/s) as LinuxCNC applies them. Only in the base/all tiers."
        ),
    )
    mcus: Optional[Dict[str, 'McuStateResponse']] = Field(
        default=None,
        description=(
            "Static MCU list from hardware.json's mcus[], keyed by MCU id. "
            "Only in the static/all tiers."
        ),
    )
    io: Optional[IoState] = Field(
        default=None,
        description="Fans, [output_pin] outputs and [input_pin] inputs. Only in the base/all tiers.",
    )
    leds: Optional[List[Led]] = Field(
        default=None,
        description="[neopixel] chains and their segment colours. Only in the base/all tiers.",
    )
