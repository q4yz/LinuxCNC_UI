from pydantic import BaseModel, Field


class HeaterCommandStateResponse(BaseModel):
    status: str = Field(default="success")
    id: str = Field(...)
    target: float = Field(...)
    command: str = Field(...)


class HeaterStateResponse(BaseModel):
    type: str = "heater"
    id: str = Field(...)
    target: float = Field(...)
    actual: float = Field(...)
    min_temp: float = Field(...)
    max_temp: float = Field(...)


class HeaterCommand(BaseModel):
    id: str = Field(..., min_length=1)
    target: float = Field(..., ge=0.0, le=400.0)


