"""``/api/v1/print-tuning`` — the live Z offset, flow, excluded objects and
the slicer's progress of the loaded print (``PrintTuningService``)."""
from __future__ import annotations

from fastapi import APIRouter

from hardware import get_stat_channel
from mappers.print_tuning.PrintTuningMapper import PrintTuningMapper
from models.PrintTuningModels import ObjectExclusion, PrintTuningState, PrintTuningUpdate
from services.program.PrintTuningService import get_print_tuning_service

router = APIRouter(prefix="/api/v1/print-tuning", tags=["print-tuning"])


def _loaded() -> tuple[str, int]:
    stat = get_stat_channel()
    if stat is None:
        return "", 0
    stat.poll()
    line = int(getattr(stat, "motion_line", 0) or getattr(stat, "current_line", 0) or 0)
    return str(getattr(stat, "file", "") or ""), line


def _state() -> PrintTuningState:
    path, line = _loaded()
    return PrintTuningMapper.to_response(get_print_tuning_service().state(path, line))


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
    if payload.pressure_advance is not None:
        service.set_pressure_advance(payload.pressure_advance)
    return _state()


@router.put("/objects/{index}", response_model=PrintTuningState, operation_id="setObjectExcluded",
            summary="Exclude an object of the loaded print (or include it again)",
            responses={400: {"description": "No such object."}})
def set_object(index: int, payload: ObjectExclusion) -> PrintTuningState:
    path, _ = _loaded()
    get_print_tuning_service().set_excluded(index, payload.excluded, path)
    return _state()
