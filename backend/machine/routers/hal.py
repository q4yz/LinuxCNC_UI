"""HTTP router for the Visual HAL editor.

Exposes the pin/signal layout for the visual canvas, and — when a
``file`` query param is given — reads/writes that *specific* ``.hal``
file's ``net`` declarations so the editor can seed itself from (and
save back to) real, on-disk machine wiring.

Pins always come from live ``halcmd`` introspection (or its mock
fallback) via :class:`HalPinSignalService` — that part of the contract
hasn't changed. Only *signals* become file-scoped: without ``file``
they're empty (there's nothing to seed from); with ``file`` they're
parsed out of that file's ``net`` lines instead of ``halcmd show sig``.

This stays a machine-backend-only concern (``.hal`` files describe a
specific machine's live wiring) — the system backend never imports
anything from this module.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException

from domain_file_services import get_machine_service
from models.hal import (
    HalFileSaveRequest,
    HalLayoutResponse,
    HalPinResource,
    HalSignalResource,
)
from services import hal_signal_file
from services.HalPinSignalService import get_hal_pin_signal_service

logger = logging.getLogger("backend.routers.hal")

router = APIRouter(prefix="/api/v1/hal", tags=["hal"])


def _placeholder_pin(full_name: str, direction: str) -> HalPinResource:
    """A pin token from the file that isn't in the live catalog.

    Expected whenever the file being edited isn't the currently-running
    config — the placeholder still renders on the canvas so the operator
    can see and rewire it. Direction is a best-effort guess (see
    :func:`_signals_from_file`), since we have no real metadata for it.
    """
    return HalPinResource(
        id=full_name,
        component_name="",
        pin_name=full_name,
        full_name=full_name,
        direction=direction,
        type="bit",
        value=None,
        description="Not present in current HAL introspection.",
    )


def _signals_from_file(file: str, in_pins: List[HalPinResource], out_pins: List[HalPinResource]) -> List[HalSignalResource]:
    pins_by_name = {p.full_name: p for p in [*in_pins, *out_pins]}
    try:
        raw = get_machine_service().read_file(file)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    signals: List[HalSignalResource] = []
    for parsed in hal_signal_file.parse_net_lines(raw):
        known = [pins_by_name.get(tok) for tok in parsed.pin_tokens]
        # Prefer a known OUT pin as the source; if none of the resolved
        # tokens is a known OUT pin, fall back to "first token is the
        # source" — the conventional `net name src => tgt tgt` ordering.
        source_idx = next((i for i, p in enumerate(known) if p is not None and p.direction == "out"), 0)

        resolved: List[HalPinResource] = []
        for i, (tok, pin) in enumerate(zip(parsed.pin_tokens, known)):
            if pin is not None:
                resolved.append(pin)
            else:
                resolved.append(_placeholder_pin(tok, "out" if i == source_idx else "in"))

        source = resolved[source_idx]
        targets = [p for i, p in enumerate(resolved) if i != source_idx]
        signals.append(
            HalSignalResource(
                name=parsed.name,
                type=source.type,
                source=source,
                targets=targets,
            )
        )
    return signals


def _build_file_layout(file: Optional[str]) -> HalLayoutResponse:
    base = get_hal_pin_signal_service().get_layout()
    if not file:
        return HalLayoutResponse(in_pins=base.in_pins, out_pins=base.out_pins, signals=[])
    signals = _signals_from_file(file, base.in_pins, base.out_pins)
    return HalLayoutResponse(in_pins=base.in_pins, out_pins=base.out_pins, signals=signals)


@router.get(
    "/layout",
    response_model=HalLayoutResponse,
    summary="Get the Visual HAL editor layout",
    description=(
        "Returns every available IN pin, OUT pin (live HAL introspection, "
        "cached), and — when `file` is given — every `net` signal declared "
        "in that specific .hal file under machine_config/machines/."
    ),
)
def get_layout(file: Optional[str] = None) -> HalLayoutResponse:
    return _build_file_layout(file)


@router.put(
    "/layout",
    response_model=HalLayoutResponse,
    summary="Save the Visual HAL editor's signals to a .hal file",
    description=(
        "Regenerates the warning-commented, marker-delimited signals "
        "section of `file` from the submitted signal list. Everything "
        "else in the file (loadrt/addf/setp/comments/hand-written HAL) "
        "is left untouched."
    ),
)
def save_layout(file: str, request: HalFileSaveRequest) -> HalLayoutResponse:
    machine_service = get_machine_service()
    try:
        raw = machine_service.read_file(file)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    new_text = hal_signal_file.apply_signals(raw, request.signals)

    try:
        machine_service.write_file(file, new_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return _build_file_layout(file)


__all__ = ["router"]
