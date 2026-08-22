from pydantic import BaseModel, Field


class TemperatureStateResponse(BaseModel):
    type: str = "sensor"
    id: str = Field(...)
    actual: float = Field(...)