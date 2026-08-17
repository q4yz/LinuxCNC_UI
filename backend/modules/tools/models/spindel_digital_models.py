from pydantic import BaseModel, Field


class SpindleDigitalCommand(BaseModel):
    tool_id: str = Field(..., min_length=1)
    action: str = Field(..., description="'forward', 'backward', or 'stop'.")
    speed: int = Field(..., ge=0, le=200_000)
    override: float = Field(default=1.0, ge=0.0, le=2.0)
    master_override: int = Field(default=0, ge=0, le=200_000)
    master_override_enable: bool = Field(default=False)


class SpindleDigitalStateResponse(BaseModel):
    type: str = "spindle_digital"
    id: str = Field(...)
    target_rpm: float = Field(0.0)
    actual_rpm: float = Field(0.0)
    is_connected: bool = Field(False)
    error_count: int = Field(0)
    last_error: str = Field("")
    spindle_at_speed: bool = Field(False)
    min_rpm: float = Field(0.0)
    max_rpm: float = Field(24000.0)
    # The frontend-friendly string representation of the direction
    state: str = Field(
        default="idle",
        description="'forward', 'backward', or 'idle'."
    )