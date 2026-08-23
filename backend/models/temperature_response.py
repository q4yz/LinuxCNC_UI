from typing import Optional

from pydantic import BaseModel, Field


class TemperatureStateResponse(BaseModel):
    type: str = "sensor"
    id: str = Field(...)
    actual: Optional[float] = Field(...)