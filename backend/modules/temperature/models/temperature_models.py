from pydantic import BaseModel, Field


class TemperatureStateResponse(BaseModel):
    type: str = "sensor"
    tool_id: str = Field(...)
    actual: float = Field(...)