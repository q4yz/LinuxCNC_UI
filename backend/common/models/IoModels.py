"""I/O API models (``/api/v1/modules/io``, `.agent/component/io_pins.md`)."""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class IoFan(BaseModel):
    id: str
    value: float = Field(..., description="Fan speed, 0 ... 100 %.")


class IoOutput(BaseModel):
    id: str
    pwm: bool = Field(..., description="PWM (slider) or switched (toggle).")
    scale: float = Field(1.0, description="A PWM output's full value (the profile's scale).")
    value: float = Field(..., description="PWM: 0 ... scale; switched: 0 or 1.")


class IoInput(BaseModel):
    id: str
    value: bool


class IoState(BaseModel):
    fans: List[IoFan] = Field(default_factory=list)
    outputs: List[IoOutput] = Field(default_factory=list)
    inputs: List[IoInput] = Field(default_factory=list)


class IoSetRequest(BaseModel):
    value: float = Field(..., description="Fan: %, PWM output: 0 ... scale, switched output: 0 / 1.")
