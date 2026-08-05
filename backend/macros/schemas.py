"""Pydantic models used by macro APIs and event streams."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class MacroSummary(BaseModel):
    name: str
    description: str = ""


class MacroContent(BaseModel):
    name: str
    body: str


class MacroRunRequest(BaseModel):
    parameters: dict[str, Any] | None = None


class MacroRunResponse(BaseModel):
    run_id: str


class MacroEvent(BaseModel):
    type: Literal["log", "gcode", "error", "done"]
    payload: dict[str, Any]