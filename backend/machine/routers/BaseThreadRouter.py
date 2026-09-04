"""Base-thread snapshot endpoint.

LinuxCNC's runtime uses two parallel threads:
* a fast **servo thread** that handles time-critical work.
* a slower **base thread** that handles bookkeeping (UI updates, status reporting).

The web UI mirrors that split via `/ws/telemetry` and this endpoint.
"""
from __future__ import annotations

from typing import Set

from fastapi import APIRouter, HTTPException, Query

from core.field_masking import ResponseTier
from models.BaseThreadStateResponse import BaseThreadSnapshotResponse
from services.BaseThreadService import get_base_thread_service

router = APIRouter(prefix="/api/v1/base-thread", tags=["Base Thread"])

_VALID_MODES = {"static", "base", "progress", "sensors", "tools", "all"}


@router.get(
    "/snapshot",
    response_model=BaseThreadSnapshotResponse,
    response_model_exclude_none=True,
    summary="Get Base-Thread Snapshot",
    description=(
            "Return the dashboard snapshot. "
            "Pass ``?mode=`` to request a specific payload tier. "
            "Valid values: ``static``, ``base``, ``all``. Omit the "
            "parameter (or pass ``all``) for the legacy full payload. "
            "``timestamp`` is always included."
    ),
    operation_id="getBaseThreadSnapshot",
)
def get_base_thread_snapshot(
        mode: str = Query(
            "all",
            description="The specific payload tier to return. Valid: static, base, all.",
        ),
) -> BaseThreadSnapshotResponse:
    """Assemble the dashboard snapshot."""

    # 1. Parse and validate HTTP request
    try:
        requested_mode = ResponseTier(mode.strip().lower())
    except ValueError:
        valid_modes = [t.value for t in ResponseTier]
        raise HTTPException(
            status_code=422,
            detail=f"Unknown mode value: '{mode}'. Valid values: {valid_modes}.",
        )

    # 2. Route to the Business Logic Service
    service = get_base_thread_service()

    if requested_mode == ResponseTier.STATIC:
        return service.get_static_response()

    if requested_mode == ResponseTier.BASE:
        return service.get_base_response()

    if requested_mode == ResponseTier.ALL:
        return service.get_snapshot()

    # Fallback just in case other enum values (like tools/sensors) are passed
    raise HTTPException(
        status_code=400,
        detail=f"Mode '{requested_mode.value}' is not supported as a standalone response."
    )


__all__ = [
    "router",
    "BaseThreadSnapshotResponse",
    "get_base_thread_snapshot",
]