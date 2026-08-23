from typing import Optional

from pydantic import BaseModel, Field


class HeaterCommandStateResponse(BaseModel):
    status: str = Field(default="success")
    id: str = Field(...)
    target: float = Field(...)
    command: str = Field(...)


class HeaterStateResponse(BaseModel):
    type: str = "heater"
    id: str = Field(...)
    target: Optional[float] = Field(...)
    actual: Optional[float] = Field(...)
    min_temp: Optional[float] = Field(...)
    max_temp: Optional[float] = Field(...)


class HeaterCommand(BaseModel):
    id: str = Field(..., min_length=1)
    target: float = Field(..., ge=0.0, le=400.0)


