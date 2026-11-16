"""``/api/v1/print-tuning`` — the live Z offset, flow, excluded objects and
the slicer's progress of the loaded print (``PrintTuningService``)."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hardware import get_stat_channel
from services.PrintTuningService import get_print_tuning_service

router = APIRouter(prefix="/api/v1/print-tuning", tags=["print-tuning"])


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
    objects: List[PrintObject] = Field(default_factory=list, description="The loaded program's objects.")
    progress: Optional[PrintProgress] = Field(None, description="From the slicer's M73 lines, if it wrote any.")


class PrintTuningUpdate(BaseModel):
    z_offset: Optional[float] = Field(None, description="Set the live Z offset (mm).")
    z_adjust: Optional[float] = Field(None, description="Change the live Z offset by this (mm).")
    flow: Optional[float] = Field(None, description="Set the flow (%), 10 … 500.")


class ObjectExclusion(BaseModel):
    excluded: bool = Field(..., description="Skip the object's remaining moves.")


def _loaded() -> tuple[str, int]:
    stat = get_stat_channel()
    if stat is None:
        return "", 0
    stat.poll()
    line = int(getattr(stat, "motion_line", 0) or getattr(stat, "current_line", 0) or 0)
    return str(getattr(stat, "file", "") or ""), line


def _state() -> PrintTuningState:
    path, line = _loaded()
    return PrintTuningState(**get_print_tuning_service().state(path, line))


@router.get("", response_model=PrintTuningState, operation_id="getPrintTuning",
            summary="Live Z offset, flow, objects and the slicer's progress")
def get_tuning() -> PrintTuningState:
    return _state()


@router.put("", response_model=PrintTuningState, operation_id="setPrintTuning",
            summary="Set / adjust the live Z offset, set the flow",
            responses={400: {"description": "Out of range."}})
def set_tuning(payload: PrintTuningUpdate) -> PrintTuningState:
    service = get_print_tuning_service()
    if payload.z_offset is not None:
        service.set_z_offset(payload.z_offset)
    if payload.z_adjust is not None:
        service.adjust_z_offset(payload.z_adjust)
    if payload.flow is not None:
        service.set_flow(payload.flow)
    return _state()


@router.put("/objects/{index}", response_model=PrintTuningState, operation_id="setObjectExcluded",
            summary="Exclude an object of the loaded print (or include it again)",
            responses={400: {"description": "No such object."}})
def set_object(index: int, payload: ObjectExclusion) -> PrintTuningState:
    path, _ = _loaded()
    get_print_tuning_service().set_excluded(index, payload.excluded, path)
    return _state()
