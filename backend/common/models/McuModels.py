from typing import List, Optional

from pydantic import BaseModel, Field


class McuResetResponse(BaseModel):
    """Outcome of ``POST /api/v1/modules/mcu/reset``."""
    status: str = Field(default="success", description="Outcome summary (e.g., 'success')")
    reset: List[str] = Field(default_factory=list, description="Ids of the MCUs whose reset pin was pulsed.")


class McuStateResponse(BaseModel):
    """JSON response model for one MCU (static machine configuration).

    Sourced from ``hardware.json``'s ``mcus[]``. Static only — it never
    changes during a machine session, so the frontend fetches it once
    via the base-thread snapshot's ``?mode=static`` tier.
    """
    id: str = Field(..., description="MCU id — the `[mcu NAME]` section name ('mcu' for a bare `[mcu]`).")
    connection: Optional[str] = Field(
        default=None,
        description="Transport the board is reached over ('remora-spi', 'parallelport', ...).",
    )
    resettable: Optional[bool] = Field(
        default=None,
        description=(
            "True when the board can be reset from the UI — a Remora MCU "
            "that declared a `reset_pin`. `POST /api/v1/modules/mcu/reset` "
            "pulses every resettable MCU's `webgui.<id>-reset` pin."
        ),
    )
