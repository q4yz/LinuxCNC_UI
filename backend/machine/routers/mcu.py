"""``/api/v1/modules/mcu`` — MCU actions.

The MCU list itself is static machine configuration and travels with
the base-thread snapshot (``?mode=static`` → ``mcus``); this router
only holds the actions.
"""
from __future__ import annotations

from fastapi import APIRouter

from models.mcu_model import McuResetResponse
from services.McuService import get_mcu_service

router = APIRouter(prefix="/api/v1/modules/mcu", tags=["modules:mcu"])


@router.post(
    "/reset",
    summary="Reset MCUs",
    description=(
        "Pulse the ``webgui.<id>-reset`` HAL pin of every resettable MCU "
        "(a Remora board that declared a ``reset_pin``). Returns ``409`` "
        "when the machine has no resettable MCU."
    ),
    operation_id="resetMcus",
    response_model=McuResetResponse,
    responses={409: {"description": "No resettable MCU on this machine."}},
)
async def reset_mcus() -> McuResetResponse:
    """``reset_mcus`` holds the pins high for the pulse width itself, so
    this handler awaits it rather than firing and forgetting."""
    ids = await get_mcu_service().reset_mcus()
    return McuResetResponse(status="success", reset=ids)


__all__ = ["router"]
