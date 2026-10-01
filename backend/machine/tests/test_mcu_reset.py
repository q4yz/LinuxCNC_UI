"""MCU reset: ``hardware.json`` ``mcus[]`` -> ``webgui.<id>-reset`` -> UI.

Only a Remora board that declared a ``reset_pin`` is resettable; the
reset endpoint pulses every such MCU's pin True -> False. Connecting
the pin to the board in ``machine.hal`` is not done yet (HAL compiler,
out of scope), so these tests stop at the pin.
"""
from __future__ import annotations

import asyncio
from typing import Any, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.field_masking import ResponseTier
from dtos.mcu.McuDto import McuPins
from dtos.pins.UnconnectedHalPin import UnconnectedHalPin
from mappers.mcu.McuMapper import McuMapper
from services import McuService as mcu_module
from services.McuService import McuService


# ---------------------------------------------------------------- #
# Mapper                                                             #
# ---------------------------------------------------------------- #


def test_remora_mcu_with_reset_pin_is_resettable():
    pins = McuMapper.from_dict_to_McuPins(
        {"id": "mcu_reset_test", "connection": "remora-spi", "reset_pin": "PC15"}
    )
    assert pins.resettable is True
    assert pins.reset.get_pin_name() == "mcu_reset_test-reset"


@pytest.mark.parametrize(
    "record",
    [
        {"id": "mcu", "connection": "remora-spi"},                      # no reset_pin
        {"id": "mcu", "connection": "parallelport", "reset_pin": "x"},  # not Remora
        {"id": "mcu", "connection": "remora-eth", "reset_pin": ""},     # empty
    ],
)
def test_other_mcus_are_not_resettable_and_get_no_pin(record):
    pins = McuMapper.from_dict_to_McuPins(record)
    assert pins.resettable is False
    assert isinstance(pins.reset, UnconnectedHalPin)


def test_response_is_static_only():
    dto = McuPins(id="mcu", connection="remora-spi", resettable=True)
    static = McuMapper.to_response(dto, ResponseTier.STATIC)
    assert (static.id, static.connection, static.resettable) == ("mcu", "remora-spi", True)

    base = McuMapper.to_response(dto, ResponseTier.BASE)
    assert base.connection is None and base.resettable is None


# ---------------------------------------------------------------- #
# Service pulse                                                      #
# ---------------------------------------------------------------- #


class _RecordingPin:
    def __init__(self) -> None:
        self.writes: List[Any] = []

    def set_value(self, value: Any) -> None:
        self.writes.append(value)


def _service_with(*mcus: McuPins) -> McuService:
    service = McuService()
    service._halpins_cache = list(mcus)
    return service


def test_reset_pulses_every_resettable_mcu_and_skips_the_rest(monkeypatch):
    sleeps: List[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(mcu_module.asyncio, "sleep", fake_sleep)

    a, b = _RecordingPin(), _RecordingPin()
    service = _service_with(
        McuPins(id="a", connection="remora-spi", resettable=True, reset=a),
        McuPins(id="pp", connection="parallelport"),
        McuPins(id="b", connection="remora-eth", resettable=True, reset=b),
    )

    assert asyncio.run(service.reset_mcus()) == ["a", "b"]
    assert a.writes == [True, False]
    assert b.writes == [True, False]
    # One shared pulse, not one per board.
    assert sleeps == [mcu_module.RESET_PULSE_S]


def test_reset_without_a_resettable_mcu_is_a_conflict():
    from exceptions import ConflictError

    service = _service_with(McuPins(id="pp", connection="parallelport"))
    with pytest.raises(ConflictError):
        asyncio.run(service.reset_mcus())


# ---------------------------------------------------------------- #
# Endpoint                                                           #
# ---------------------------------------------------------------- #


def _client(service: McuService, monkeypatch) -> TestClient:
    from routers import mcu as mcu_router

    monkeypatch.setattr(mcu_router, "get_mcu_service", lambda: service)
    app = FastAPI()
    app.include_router(mcu_router.router)
    return TestClient(app)


def test_reset_endpoint_returns_the_reset_ids(monkeypatch):
    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(mcu_module.asyncio, "sleep", fake_sleep)
    pin = _RecordingPin()
    service = _service_with(McuPins(id="mcu", connection="remora-spi", resettable=True, reset=pin))

    resp = _client(service, monkeypatch).post("/api/v1/modules/mcu/reset")
    assert resp.status_code == 200
    assert resp.json() == {"status": "success", "reset": ["mcu"]}
    assert pin.writes == [True, False]


def test_reset_endpoint_409_without_a_resettable_mcu(monkeypatch):
    service = _service_with(McuPins(id="pp", connection="parallelport"))
    resp = _client(service, monkeypatch).post("/api/v1/modules/mcu/reset")
    assert resp.status_code == 409
