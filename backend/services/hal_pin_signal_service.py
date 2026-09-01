"""HAL pin / signal reader for the Visual HAL editor.

The hardware pin set is static while LinuxCNC is running —
components are created at startup and never change — so reading
them through ``hal`` on every request is wasted work. This service
therefore caches the mapped :class:`HalLayoutResponse` after the
first read and returns the cached object forever after
(:meth:`HalPinSignalService.get_layout`).

The actual ``linuxcnc`` / ``hal`` library calls are stubbed for
now: :meth:`_read_pins_from_linuxcnc` and
:meth:`_read_signals_from_linuxcnc` return a hardcoded mock
representation (boolean and float pins) that mirrors what
``hal-pins``/``hal-signals`` introspection would produce. When the
real integration lands, only those two private methods change —
the caching contract and everything above it stays identical.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from dtos.pins.HalPin import HalDirection
from dtos.pins.MachineHalPin import MachineHalPin
from dtos.pins.MachineSignal import MachineHalSignal
from mappers.hal_mapper import HalMapper
from models.hal import HalLayoutResponse

logger = logging.getLogger("backend.services.hal_pin_signal")


def _pin(name: str, comp: str, value, direction: HalDirection, doc: str = "") -> MachineHalPin:
    """Shorthand for building a mock :class:`MachineHalPin`."""
    return MachineHalPin(
        value=value,
        pin=name,
        component_name=comp,
        description=doc,
        direction=direction,
    )


class HalPinSignalService:
    """Reads (once) and caches the HAL pin/signal layout for the visual editor."""

    def __init__(self) -> None:
        self._layout_cache: Optional[HalLayoutResponse] = None

    def get_layout(self) -> HalLayoutResponse:
        """Return the full editor layout, reading hardware at most once.

        The first call delegates to :meth:`_build_layout`; every
        later call short-circuits on ``self._layout_cache``.
        """
        if self._layout_cache is None:
            self._layout_cache = self._build_layout()
            logger.info(
                "HAL layout cached: %d IN pins, %d OUT pins, %d signals",
                len(self._layout_cache.in_pins),
                len(self._layout_cache.out_pins),
                len(self._layout_cache.signals),
            )
        return self._layout_cache

    def reset_cache(self) -> None:
        """Drop the cached layout (used by tests and future reload flows)."""
        self._layout_cache = None

    # ------------------------------------------------------------------ #
    # Internal assembly                                                   #
    # ------------------------------------------------------------------ #

    def _build_layout(self) -> HalLayoutResponse:
        """Read pins + signals from the (stubbed) HAL and map them.

        The pin set is read exactly once and handed to the signal
        reader so both halves of the layout describe the same pin
        objects (and a layout build costs a single introspection
        pass).
        """
        pins = self._read_pins_from_linuxcnc()
        signals = self._read_signals_from_linuxcnc(pins)
        return HalMapper.to_layout(pins, signals)

    # ------------------------------------------------------------------ #
    # LinuxCNC introspection stubs                                        #
    # ------------------------------------------------------------------ #

    def _read_pins_from_linuxcnc(self) -> List[MachineHalPin]:
        """Stub for the real ``hal`` pin introspection.

        TODO: replace with the ``linuxcnc`` / ``hal`` library call
        (``hal.components()`` + ``comp.pins()`` introspection) when
        running against a live HAL. Returns a hardcoded, realistic
        mix of boolean (bit) and float pins in both directions.
        """
        return [
            # OUT pins (writers) — right-hand palette
            _pin("spindle-on", "motion", True, HalDirection.OUT, "Spindle forward command from the trajectory planner"),
            _pin("spindle-speed-out", "motion", 1200.0, HalDirection.OUT, "Commanded spindle speed [RPM]"),
            _pin("coolant-mist", "motion", False, HalDirection.OUT, "Mist coolant command"),
            _pin("x-pos-cmd", "axis", 0.0, HalDirection.OUT, "X axis commanded position [mm]"),
            _pin("feed-cmd", "motion", 0.0, HalDirection.OUT, "Commanded feed rate [mm/min]"),
            _pin("at-speed", "spindle", False, HalDirection.OUT, "VFD feedback: spindle reached the commanded speed"),
            # IN pins (readers) — left-hand palette
            _pin("spindle-at-speed", "motion", False, HalDirection.IN, "Motion controller reads the at-speed feedback"),
            _pin("x-pos-fb", "spindle", 0.0, HalDirection.IN, "Drive-side X axis position input [mm]"),
            _pin("estop-in", "iocontrol", True, HalDirection.IN, "Physical E-STOP chain state (True = released)"),
            _pin("spindle-brake-in", "spindle", False, HalDirection.IN, "Spindle brake engage request from hardware"),
            _pin("toolchanger-ready", "toolchanger", False, HalDirection.IN, "Toolchanger is ready to accept a change"),
        ]

    def _read_signals_from_linuxcnc(
        self, pins: Optional[List[MachineHalPin]] = None
    ) -> List[MachineHalSignal]:
        """Stub for the real ``hal`` signal introspection.

        TODO: replace with the ``hal`` signal listing when running
        against a live HAL. Returns two pre-wired signals so the
        editor's middle column renders meaningful content; the
        already-read pin list is reused so a layout build performs
        exactly one pin introspection pass.
        """
        if pins is None:
            pins = self._read_pins_from_linuxcnc()
        pins_by_name = {p.get_pin_name(): p for p in pins}
        return [
            MachineHalSignal(
                name="spindle-at-speed-sig",
                source=pins_by_name["at-speed"],
                targets=(pins_by_name["spindle-at-speed"],),
                description="VFD at-speed feedback routed into the motion controller",
            ),
            MachineHalSignal(
                name="x-position-sig",
                source=pins_by_name["x-pos-cmd"],
                targets=(pins_by_name["x-pos-fb"],),
                description="X axis command routed to the drive's position input",
            ),
        ]


# Singleton Provider
_SERVICE_INSTANCE = None


def get_hal_pin_signal_service() -> HalPinSignalService:
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = HalPinSignalService()
    return _SERVICE_INSTANCE
