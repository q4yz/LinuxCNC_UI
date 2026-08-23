from typing import Optional

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
    target_rpm: Optional[float] = Field(0.0)
    actual_rpm: Optional[float] = Field(0.0)
    is_connected: Optional[bool] = Field(False)
    error_count: Optional[int] = Field(0)
    last_error: Optional[str] = Field("")
    spindle_at_speed: Optional[bool] = Field(False)
    min_rpm: Optional[float] = Field(0.0)
    max_rpm: Optional[float] = Field(24000.0)
    master_override_enable: Optional[bool] = Field(False)
    state: Optional[str] = Field(
        default="idle",
        description="'forward', 'backward', or 'idle'."
    )

