"""HTTP router for the Visual HAL editor.

A flat, standalone surface — deliberately independent from the
text-based machine-config editor. Exposes a single read-only
endpoint returning every available IN pin, OUT pin, and existing
signal so the frontend can render the three-column editor in one
request.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from models.hal import HalLayoutResponse
from services.hal_pin_signal_service import get_hal_pin_signal_service

logger = logging.getLogger("backend.routers.hal")

router = APIRouter(prefix="/api/v1/hal", tags=["hal"])


@router.get(
    "/layout",
    response_model=HalLayoutResponse,
    summary="Get the Visual HAL editor layout",
    description=(
        "Returns every available IN pin, OUT pin, and existing HAL "
        "signal. The hardware pin set is static during runtime, so "
        "the service caches the layout after the first read and "
        "serves the cached object on subsequent calls."
    ),
)
def get_layout() -> HalLayoutResponse:
    """Serve the (cached) pin + signal layout for the visual editor."""
    return get_hal_pin_signal_service().get_layout()


__all__ = ["router"]
