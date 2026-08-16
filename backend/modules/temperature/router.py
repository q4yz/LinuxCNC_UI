"""HTTP router for the temperature module (DEPRECATED).

This router is mounted by the registry under ``/api/v1/modules/temperature``.
It exists solely to intercept legacy requests from older frontends and
safely redirect them to the new Domain-Driven Tools module.

All live telemetry (reading temperatures) and hardware dispatch (setting
targets) is now handled natively by the `tools` module and the core
`TemperatureService`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from starlette import status

logger = logging.getLogger("backend.modules.temperature.router")

router = APIRouter()

@router.post(
    "/sensors/{name}/target",
    summary="DEPRECATED: Set Sensor Target Temperature",
    description=(
            "DEPRECATED: This endpoint is no longer active. All heating "
            "and temperature dispatching has been moved to the Domain-Driven "
            "Tools module."
    ),
    deprecated=True,
)
def set_target(name: str, req: Any) :
    """Set the target temperature for ``name`` (DEPRECATED)."""

    # Do not execute any hardware commands.
    # Immediately reject the request and point the caller to the new router.
    raise HTTPException(
        status_code=status.HTTP_410_GONE,  # 410 is the standard HTTP code for "endpoint removed"
        detail=(
            f"This endpoint has been removed. Please use the new tools endpoint "
            f"to set temperatures: POST /api/v1/modules/tools/{name}/target"
        )
    )


__all__ = [
    "router",
]