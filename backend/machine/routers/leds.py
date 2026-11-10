"""``/api/v1/leds`` — WS2812 / SK6812 LED chains (`.agent/component/neopixel.md`)."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Path
from pydantic import BaseModel, Field

from core.led_color import SetLed
from models.LedModels import Led, LedSegment
from services.LedService import get_led_service

router = APIRouter(prefix="/api/v1/leds", tags=["leds"])



class LedSetRequest(BaseModel):
    """Klipper's ``SET_LED`` parameters, 0.0 ... 1.0."""

    red: float = Field(0.0, ge=0.0, le=1.0)
    green: float = Field(0.0, ge=0.0, le=1.0)
    blue: float = Field(0.0, ge=0.0, le=1.0)
    white: float = Field(0.0, ge=0.0, le=1.0, description="Added to R, G, B (an RGBW chip's white LED).")
    index: Optional[int] = Field(None, ge=1, description="LED number from 1: its segment. None: the whole chain.")


@router.get("", response_model=List[Led], operation_id="getLeds", summary="LED chains and their colours")
def get_leds() -> List[Led]:
    return [Led(**led) for led in get_led_service().state()]


@router.put("/{led_id}", response_model=List[Led], operation_id="setLed",
            summary="Set an LED chain's colour (Klipper's SET_LED)",
            responses={404: {"description": "No such LED."}, 400: {"description": "INDEX outside the chain."}})
def set_led(payload: LedSetRequest, led_id: str = Path(..., description="The [neopixel] name.")) -> List[Led]:
    command = SetLed(led=led_id, red=payload.red, green=payload.green, blue=payload.blue,
                     white=payload.white, index=payload.index)
    return [Led(**led) for led in get_led_service().set(command)]


__all__ = ["Led", "LedSegment", "router"]
