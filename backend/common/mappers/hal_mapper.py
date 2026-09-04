"""Maps pure HAL DTOs into the Visual HAL editor's JSON resources.

Stays deliberately dumb: no I/O, no caching — just field-for-field
translation from :class:`dtos.pins.MachineHalPin` /
:class:`dtos.pins.MachineHalSignal` into the Pydantic resources in
:mod:`models.hal`. The service layer owns when (and how often) the
DTOs are read; this mapper only shapes them.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Sequence

from dtos.pins.HalPin import HalDirection
from dtos.pins.MachineHalPin import MachineHalPin
from dtos.pins.MachineSignal import MachineHalSignal
from models.hal import HalLayoutResponse, HalPinResource, HalSignalResource

# Python type of the DTO ``value`` field -> HAL data-type token.
# ``bool`` must be checked before ``int`` — bool is a subclass of
# int in Python, so the naive isinstance chain would classify
# ``True`` as ``s32``.
_TYPE_BY_KIND = (
    (bool, "bit"),
    (float, "float"),
    (int, "s32"),
)


class HalMapper:
    """Static DTO -> Pydantic-resource translation for the visual editor."""

    @staticmethod
    def infer_hal_type(value: Any) -> str:
        """Derive the HAL data-type token from a pin's Python value.

        Unknown types fall back to ``float`` — the least lossy HAL
        type — so the editor still renders the pin instead of
        crashing on an exotic component.
        """
        for kind, token in _TYPE_BY_KIND:
            if isinstance(value, kind):
                return token
        return "float"

    @staticmethod
    def pin_full_name(pin: MachineHalPin[Any]) -> str:
        """``<component>.<pin>``; tolerates a missing component."""
        comp = pin.get_comp_name()
        name = pin.get_pin_name()
        if comp and name:
            return f"{comp}.{name}"
        return name or comp

    @staticmethod
    def to_pin_resource(pin: MachineHalPin[Any]) -> HalPinResource:
        """Flatten one :class:`MachineHalPin` into a :class:`HalPinResource`."""
        full_name = HalMapper.pin_full_name(pin)
        direction = pin.get_direction()
        return HalPinResource(
            id=full_name,
            component_name=pin.get_comp_name(),
            pin_name=pin.get_pin_name(),
            full_name=full_name,
            direction=direction.value if isinstance(direction, HalDirection) else str(direction),
            type=HalMapper.infer_hal_type(pin.get_value()),
            value=pin.get_value(),
            description=pin.get_doc_string(),
        )

    @staticmethod
    def to_signal_resource(signal: MachineHalSignal[Any]) -> HalSignalResource:
        """Flatten one :class:`MachineHalSignal` into a :class:`HalSignalResource`.

        The signal's type token is derived from its source pin when
        one is connected, otherwise from its first target — an empty
        signal defaults to ``bit``.
        """
        source = HalMapper.to_pin_resource(signal.source) if signal.source is not None else None
        targets = [HalMapper.to_pin_resource(t) for t in signal.targets]

        type_ref: Any = None
        if signal.source is not None:
            type_ref = signal.source.get_value()
        elif signal.targets:
            type_ref = signal.targets[0].get_value()
        type_token = HalMapper.infer_hal_type(type_ref) if type_ref is not None else "bit"

        return HalSignalResource(
            name=signal.name,
            type=type_token,
            source=source,
            targets=targets,
            description=signal.description,
        )

    @staticmethod
    def to_layout(
        pins: Sequence[MachineHalPin[Any]],
        signals: Iterable[MachineHalSignal[Any]],
    ) -> HalLayoutResponse:
        """Split pins into IN/OUT palettes and map every signal.

        ``IO``-style pins (neither :attr:`HalDirection.IN` nor
        ``OUT``) are treated as OUT pins so they stay droppable as
        writers in the editor.
        """
        in_pins: List[HalPinResource] = []
        out_pins: List[HalPinResource] = []
        for pin in pins:
            resource = HalMapper.to_pin_resource(pin)
            if pin.get_direction() == HalDirection.IN:
                in_pins.append(resource)
            else:
                out_pins.append(resource)
        signal_resources = [HalMapper.to_signal_resource(s) for s in signals]
        return HalLayoutResponse(
            in_pins=in_pins,
            out_pins=out_pins,
            signals=signal_resources,
        )
