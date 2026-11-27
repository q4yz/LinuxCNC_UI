"""``/api/v1/ace`` — the ACE Pro filament unit (``services.filament.AceService``).

A tool change goes through MDI (``M640 P<slot>``) so the motion half —
park, cut, purge — runs too; the other commands talk to the unit only."""
from __future__ import annotations

from core import ace_contract
from exceptions import ConflictError
from fastapi import APIRouter, Path
from models.AceModels import (
    AceChangeRequest,
    AceCurrentRequest,
    AceDryRequest,
    AceMoveRequest,
    AceStateResponse,
)
from services.filament.AceService import get_ace_service

router = APIRouter(prefix="/api/v1/ace", tags=["ace"])

_INDEX = Path(..., ge=0, le=3, description="The slot, 0-3.")


@router.get("", response_model=AceStateResponse, operation_id="getAceState",
            summary="The ACE: link, slots, dryer, loaded slot, sensors")
def get_state() -> AceStateResponse:
    return get_ace_service().state()


@router.post("/change", response_model=AceStateResponse, operation_id="aceChangeTool",
             summary="Load a slot (or -1: unload) — runs M640 (park, cut, change, purge)",
             responses={409: {"description": "No [ace], or a change is running."}})
def change(payload: AceChangeRequest) -> AceStateResponse:
    service = get_ace_service()
    if not service.configured:
        raise ConflictError("This machine has no [ace] in its profile.")
    if service.changing:
        raise ConflictError("A tool change is running.")
    from services.machine.StateService import get_state_service

    get_state_service().run_mdi(f"{ace_contract.M_CODE} P{payload.slot}")
    return service.state()


@router.post("/slots/{index}/feed", response_model=AceStateResponse, operation_id="aceFeed",
             summary="Push filament of a slot towards the printer (setup)")
async def feed(payload: AceMoveRequest, index: int = _INDEX) -> AceStateResponse:
    service = get_ace_service()
    await service.feed(index, payload.length, payload.speed)
    return service.state()


@router.post("/slots/{index}/unwind", response_model=AceStateResponse, operation_id="aceUnwind",
             summary="Pull filament of a slot back (setup)")
async def unwind(payload: AceMoveRequest, index: int = _INDEX) -> AceStateResponse:
    service = get_ace_service()
    await service.unwind(index, payload.length, payload.speed)
    return service.state()


@router.post("/dryer", response_model=AceStateResponse, operation_id="aceStartDrying",
             summary="Start drying (°C, minutes)")
async def start_drying(payload: AceDryRequest) -> AceStateResponse:
    service = get_ace_service()
    await service.start_drying(payload.temp, payload.minutes)
    return service.state()


@router.delete("/dryer", response_model=AceStateResponse, operation_id="aceStopDrying", summary="Stop drying")
async def stop_drying() -> AceStateResponse:
    service = get_ace_service()
    await service.stop_drying()
    return service.state()


@router.put("/current", response_model=AceStateResponse, operation_id="aceSetCurrentSlot",
            summary="Say which slot is really loaded (after loading / unloading by hand)")
def set_current(payload: AceCurrentRequest) -> AceStateResponse:
    service = get_ace_service()
    service.set_current(payload.slot)
    return service.state()
