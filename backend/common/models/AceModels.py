"""``/api/v1/ace`` — the ACE Pro filament unit (``services.filament.AceService``)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AceSlotResponse(BaseModel):
    index: int = Field(..., description="0-based; the slicer's T<index>.")
    status: str = Field(..., description="'ready' = filament there, 'empty', or what the ACE reports.")
    type: str = ""
    brand: str = ""
    sku: str = ""
    color: list[int] | None = Field(None, description="[r, g, b] from the RFID tag, if any.")
    rfid: int = Field(0, description="0 not found, 1 failed, 2 identified, 3 identifying.")


class AceDryerResponse(BaseModel):
    drying: bool
    target_temp: float | None = None
    remain_min: float | None = None
    duration_min: float | None = None


class AceStateResponse(BaseModel):
    configured: bool = Field(..., description="The machine's profile has an [ace].")
    connected: bool = False
    model: str = ""
    firmware: str = ""
    status: str = Field("", description="The ACE: 'ready' or 'busy'.")
    action: str = Field("", description="What it is busy with: feeding, unwinding, ...")
    temp: float | None = Field(None, description="Inside the unit (°C).")
    slots: list[AceSlotResponse] = Field(default_factory=list)
    dryer: AceDryerResponse | None = None
    current_slot: int = Field(-1, description="The loaded slot: -1 none, -2 unknown.")
    changing: bool = Field(False, description="A tool change (M640) is running.")
    step: str = Field("", description="What the change is doing now.")
    toolhead_sensor: bool | None = Field(None, description="Filament at the toolhead sensor (None: unreadable).")
    hub_sensor: bool | None = Field(None, description="Filament at the hub sensor (None: none or unreadable).")
    last_error: str = Field("", description="The last failed change or the link error.")


class AceChangeRequest(BaseModel):
    slot: int = Field(..., ge=-1, le=3, description="The slot to load; -1 unloads.")


class AceMoveRequest(BaseModel):
    length: float = Field(..., gt=0, le=2000, description="mm")
    speed: float = Field(25.0, gt=0, le=80, description="mm/s")


class AceDryRequest(BaseModel):
    temp: float = Field(..., gt=0, le=55, description="°C")
    minutes: int = Field(..., ge=1, le=240)


class AceCurrentRequest(BaseModel):
    slot: int = Field(..., ge=-1, le=3, description="The slot that is really loaded (-1: none).")


__all__ = [
    "AceChangeRequest", "AceCurrentRequest", "AceDryRequest", "AceDryerResponse", "AceMoveRequest",
    "AceSlotResponse", "AceStateResponse",
]
