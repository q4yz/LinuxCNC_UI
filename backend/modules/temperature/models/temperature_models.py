from pydantic import BaseModel, Field


class TemperatureStateResponse(BaseModel):
    tool_id: str = Field(...)
    actual: float = Field(...)