"""Pydantic models used by macro APIs and event streams."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class MacroSummary(BaseModel):
    name: str
    description: str | None = None


class MacroContent(BaseModel):
    name: str
    body: str


class MacroRunRequest(BaseModel):
    parameters: dict[str, Any] | None = None


class MacroRunResponse(BaseModel):
    run_id: str
    status: str


class MacroEvent(BaseModel):
    type: Literal["log", "gcode", "error"]
    payload: dict[str, Any]
