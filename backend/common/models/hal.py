"""JSON contract for the Visual HAL editor.

The visual editor is a fully independent feature: it never touches
the text-based configuration editor's models. The resources below
are flattened, frontend-friendly snapshots of the pure
``MachineHalPin`` / ``MachineHalSignal`` DTOs
(:mod:`dtos.pins.MachineHalPin` / :mod:`dtos.pins.MachineSignal`):

* ``id`` / ``full_name`` are pre-computed so the UI never has to
  concatenate component + pin names itself.
* ``direction`` is the lowercase ``"in"`` / ``"out"`` token the
  DTO's :class:`HalDirection` enum already uses.
* ``type`` is the HAL data-type token (``bit`` / ``float`` /
  ``s32`` / ``u32``) the frontend needs for drop validation.
"""

from __future__ import annotations

from typing import List, Optional, Union

from pydantic import BaseModel, Field

HalPinValue = Union[bool, int, float]


class HalPinResource(BaseModel):
    """A single HAL pin as rendered in the drag-and-drop palette."""

    id: str = Field(
        ...,
        description="Stable unique key (``<component>.<pin>``) used by the UI for drag payloads and lookups.",
    )
    component_name: str = Field("", description="HAL component that owns the pin.")
    pin_name: str = Field("", description="Bare pin name without the component prefix.")
    full_name: str = Field(
        ...,
        description="Fully-qualified pin name (``<component>.<pin>``) as shown to the operator.",
    )
    direction: str = Field(
        ...,
        description="Pin direction: ``in`` pins read a signal, ``out`` pins write one.",
    )
    type: str = Field(
        ...,
        description="HAL data type token: ``bit``, ``float``, ``s32`` or ``u32``.",
    )
    value: Optional[HalPinValue] = Field(
        None,
        description="Last known pin value (bool for bit pins, number for the numeric types).",
    )
    description: str = Field("", description="Human-readable documentation string.")


class HalSignalResource(BaseModel):
    """A HAL signal (wire) connecting one source OUT pin to N target IN pins."""

    name: str = Field(..., description="Signal name as known to LinuxCNC.")
    type: str = Field(
        "bit",
        description="HAL data type token carried by the signal (``bit``/``float``/``s32``/``u32``).",
    )
    source: Optional[HalPinResource] = Field(
        None,
        description="The single OUT pin writing the signal, if one is connected.",
    )
    targets: List[HalPinResource] = Field(
        default_factory=list,
        description="Every IN pin reading the signal (HAL allows many readers).",
    )
    description: str = Field("", description="Human-readable documentation string.")


class HalLayoutResponse(BaseModel):
    """Payload of ``GET /api/v1/hal/layout`` — the editor's full world state."""

    in_pins: List[HalPinResource] = Field(
        default_factory=list,
        description="Every available IN (reader) pin for the left-hand palette.",
    )
    out_pins: List[HalPinResource] = Field(
        default_factory=list,
        description="Every available OUT (writer) pin for the right-hand palette.",
    )
    signals: List[HalSignalResource] = Field(
        default_factory=list,
        description="Every existing signal (wire) for the middle column.",
    )


class HalFileSignalWrite(BaseModel):
    """One signal as submitted by the editor when saving to a ``.hal`` file.

    Pins are referenced by their plain ``full_name`` string (e.g.
    ``"vfdmod.spindle.at-speed"``) rather than a full
    :class:`HalPinResource` — the file writer only ever needs the name to
    render a ``net`` line.
    """

    name: str = Field(..., description="Signal name to write as the ``net`` name.")
    source: Optional[str] = Field(
        None, description="Full name of the single OUT pin driving this signal."
    )
    targets: List[str] = Field(
        default_factory=list,
        description="Full names of every IN pin reading this signal.",
    )


class HalFileSaveRequest(BaseModel):
    """Body of ``PUT /api/v1/hal/layout`` — the editor's current signal set."""

    signals: List[HalFileSignalWrite] = Field(default_factory=list)
