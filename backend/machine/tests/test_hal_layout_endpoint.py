"""Tests for the Visual HAL editor's ``GET /api/v1/hal/layout``.

The router is mounted alone on a fresh FastAPI app (same pattern
as ``test_temperature_router.py``) so every test exercises exactly
the visual-editor surface. The critical contract pinned here is
the **cache**: hardware pins do not change during runtime, so the
service must read them once and serve the cached layout forever
after — the stub reader is monkeypatched with a counter to prove
the second HTTP request never triggers a second read.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.HalPinSignalService import HalPinSignalService


def _build_router_app() -> FastAPI:
    """Fresh app with only the HAL router mounted — keeps the
    surface small so each test exercises the layout endpoint in
    isolation (no telemetry loop, no other domains).
    """
    from routers.hal import router as hal_router

    app = FastAPI()
    app.include_router(hal_router)
    return app


def _client() -> TestClient:
    return TestClient(_build_router_app())


def _counting_reads(service: HalPinSignalService):
    """Wrap the service's two stub readers with call counters.

    Returns ``(pins_calls, signals_calls)`` — zero-arg callables
    reporting how many times each reader ran.
    """
    real_pins = service._read_pins_from_linuxcnc
    real_signals = service._read_signals_from_linuxcnc

    def counting_pins():
        pins_calls.count += 1
        return real_pins()

    def counting_signals(*args, **kwargs):
        signals_calls.count += 1
        return real_signals(*args, **kwargs)

    pins_calls = SimpleNamespace(count=0)
    signals_calls = SimpleNamespace(count=0)

    # Patch the bound methods on the instance; ``get_layout`` calls
    # ``self._read_pins_from_linuxcnc()`` so the instance attribute
    # shadows the class method.
    service._read_pins_from_linuxcnc = counting_pins
    service._read_signals_from_linuxcnc = counting_signals
    return lambda: pins_calls.count, lambda: signals_calls.count


def test_layout_endpoint_returns_three_sections():
    client = _client()
    response = client.get("/api/v1/hal/layout")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"in_pins", "out_pins", "signals"}
    assert len(body["in_pins"]) > 0
    assert len(body["out_pins"]) > 0
    # Without a `file` param there's nothing to seed signals from —
    # signals are now file-scoped (see test_hal_file_signals.py).
    assert body["signals"] == []


def test_layout_endpoint_direction_and_type_tokens():
    client = _client()
    body = client.get("/api/v1/hal/layout").json()

    for pin in body["in_pins"]:
        assert pin["direction"] == "in"
    for pin in body["out_pins"]:
        assert pin["direction"] == "out"

    # The mock mixes bit and float pins; both palettes must expose
    # the full token set the frontend validates against.
    all_types = {p["type"] for p in body["in_pins"] + body["out_pins"]}
    assert {"bit", "float"} <= all_types


def test_layout_endpoint_signal_shape():
    # Signals are file-scoped now (empty without `file`); shape is
    # covered end-to-end in test_hal_file_signals.py. This test just
    # pins that the field survives on a signal-less response.
    client = _client()
    body = client.get("/api/v1/hal/layout").json()
    assert body["signals"] == []


def test_layout_is_cached_after_first_read():
    """Two GETs must trigger exactly one hardware read.

    The hardware pin set is static during runtime; the service is
    required to cache the layout on the first request. A second
    read here would be a regression of that contract.
    """
    from services.HalPinSignalService import get_hal_pin_signal_service

    service = get_hal_pin_signal_service()
    service.reset_cache()
    pins_calls, signals_calls = _counting_reads(service)

    client = _client()

    first = client.get("/api/v1/hal/layout")
    assert first.status_code == 200
    assert pins_calls() == 1
    assert signals_calls() == 1

    second = client.get("/api/v1/hal/layout")
    assert second.status_code == 200
    assert second.json() == first.json()
    assert pins_calls() == 1
    assert signals_calls() == 1


def test_reset_cache_forces_a_reread():
    from services.HalPinSignalService import get_hal_pin_signal_service

    service = get_hal_pin_signal_service()
    service.reset_cache()
    pins_calls, _ = _counting_reads(service)

    client = _client()
    client.get("/api/v1/hal/layout")
    assert pins_calls() == 1

    service.reset_cache()
    client.get("/api/v1/hal/layout")
    assert pins_calls() == 2
