from typing import Literal, Optional

from pydantic import BaseModel, Field

from modules.tools.models.heater_models import HeaterCommand, HeaterStateResponse


class ExtruderCommand(BaseModel):
    tool_id: str = Field(..., min_length=1)
    action: str = Field(..., description="'extrude' or 'retract'.")
    distance: float = Field(..., gt=0.0, le=1000.0)
    speed: int = Field(..., gt=0, le=10_000)
    heater: Optional[HeaterCommand] = Field(
        default=None,
        description=(
            "Optional embedded heater command. ``None`` skips the "
            "heater dispatch entirely — the historical contract "
            "didn't include this field; making it optional keeps "
            "older frontends that just extrude/retract working."
        ),
    )
    heater_action: Literal["set", "noop"] = Field(
        default="noop",
        description=(
            "How to apply the embedded heater command. ``noop`` "
            "(default) skips the heater dispatch; ``set`` dispatches "
            "the heater target before the move. Defaults to ``noop`` "
            "to match the historical test contract where the heater "
            "command was not part of the request payload."
        ),
    )

class ExtruderStateResponse(BaseModel):
    """Extruder response containing a fully composed heater state."""
    id: str = Field(...)
    heater: HeaterStateResponse = Field(..., description="The embedded heater state.")
    position: float = Field(0.0)
