from typing import Literal

from pydantic import BaseModel, Field

from modules.tools.models.heater_models import HeaterCommand, HeaterStateResponse


class ExtruderCommand(BaseModel):
    tool_id: str = Field(..., min_length=1)
    action: str = Field(..., description="'extrude' or 'retract'.")
    distance: float = Field(..., gt=0.0, le=1000.0)
    speed: int = Field(..., gt=0, le=10_000)
    heater: HeaterCommand
    heater_action: Literal["set", "noop"] = Field(
        default="set",
        description=(
            "How to apply the embedded heater command. ``set`` "
            "(default) dispatches the heater target before the move. "
            "``noop`` skips the heater dispatch entirely — the "
            "``heater`` field is still required so the contract "
            "stays uniform, but its ``target`` is ignored. This "
            "lets the operator extrude or retract without "
            "implicitly toggling the heater back on."
        ),
    )

class ExtruderStateResponse(BaseModel):
    """Extruder response containing a fully composed heater state."""
    id: str = Field(...)
    heater: HeaterStateResponse = Field(..., description="The embedded heater state.")
    position: float = Field(0.0)
