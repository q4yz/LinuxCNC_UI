"""Print tuning API models (``/api/v1/print-tuning``)."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class PrintObject(BaseModel):
    index: int = Field(..., description="The object's number (webgui.exclude-object-<index>).")
    name: str = Field(..., description="The object's name from the slicer.")
    excluded: bool = Field(False, description="Its remaining moves are skipped.")


class PrintProgress(BaseModel):
    percent: Optional[float] = Field(None, description="The slicer's progress (M73 P).")
    remaining_min: Optional[float] = Field(None, description="The slicer's time left in minutes (M73 R).")


class PrintTuningState(BaseModel):
    z_offset: float = Field(..., description="Live Z offset (mm).")
    flow: float = Field(..., description="Flow (%).")
    pressure_advance: float = Field(0.0, description="Pressure advance (mm per mm/s).")
    objects: List[PrintObject] = Field(default_factory=list, description="The loaded program's objects.")
    progress: Optional[PrintProgress] = Field(None, description="From the slicer's M73 lines, if it wrote any.")


class PrintTuningUpdate(BaseModel):
    z_offset: Optional[float] = Field(None, description="Set the live Z offset (mm).")
    z_adjust: Optional[float] = Field(None, description="Change the live Z offset by this (mm).")
    flow: Optional[float] = Field(None, description="Set the flow (%), 10 … 500.")
    pressure_advance: Optional[float] = Field(None, description="Set the pressure advance (mm per mm/s), 0 … 2.")


class ObjectExclusion(BaseModel):
    excluded: bool = Field(..., description="Skip the object's remaining moves.")


__all__ = ["ObjectExclusion", "PrintObject", "PrintProgress", "PrintTuningState", "PrintTuningUpdate"]
