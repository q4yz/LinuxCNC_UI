"""The parsed form of a pin string, and what an MCU can do with one.

A pin value in ``hardware.json`` is a Klipper-style string — the source
format the profiles are written in:

    [modifiers][<mcu_id>:]<pin_id>

``!PF14`` (inverted), ``^PC0`` (pull-up), ``par0:02`` (explicit MCU),
``PE3`` (bare). See ``.agent/component/README.md`` § 1 for the grammar
and § 2 for the capability classes.

These are compile-time concerns: the pin string says where a signal is
physically wired, which is what the HAL compiler needs to route it. The
runtime never looks at them — it reads values off named HAL pins.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

#: The MCU a pin belongs to when the string carries no ``<mcu>:`` prefix.
DEFAULT_MCU_ID = "mcu"


@dataclass(frozen=True, slots=True)
class ParsedPin:
    """One pin string, split into its parts.

    ``raw`` is kept so diagnostics can quote exactly what the operator
    wrote rather than a normalised form they would not recognise.
    """

    raw: str
    mcu_id: str
    pin_id: str
    invert: bool = False
    pullup: bool = False
    pulldown: bool = False

    @property
    def qualified(self) -> str:
        """``"<mcu_id>:<pin_id>"`` — the identity used for conflict checks."""
        return f"{self.mcu_id}:{self.pin_id}"


class CapabilityClass(Enum):
    """What kind of motion an MCU can carry (README § 2).

    This decides what a component may emit at all — a stepper on a
    class B board must not get a software ``stepgen``, and a joint on a
    class C board is a hard error, not a slow machine.
    """

    #: Software ``stepgen`` makes the pulses; the MCU is a pin driver.
    STEP_DIR = "A"
    #: The board runs its own motion engine off a position setpoint.
    POSITION = "B"
    #: No motion at all — I/O only.
    IO_ONLY = "C"

    @classmethod
    def for_connection(cls, connection: str | None) -> "CapabilityClass | None":
        """Map an ``mcus[].connection`` value onto a class.

        Returns ``None`` for an unrecognised transport so the caller
        can report it rather than guessing a class and emitting HAL
        that silently does the wrong thing.
        """
        return {
            "parallelport": cls.STEP_DIR,
            "remora-spi": cls.POSITION,
            "remora-eth": cls.POSITION,
            # An EtherCAT servo drive closes its own position loop from a
            # cyclic setpoint (mcu_ethercat.md) — class B like Remora.
            "ethercat": cls.POSITION,
            # A VFD on a serial bus is a controller, so it is an MCU —
            # but a peripheral one. It can carry a spindle, never a
            # joint. ``rs485`` is the pre-rename alias.
            "vfd_rs485": cls.IO_ONLY,
            "rs485": cls.IO_ONLY,
            # A USB-serial Arduino bridge is userspace I/O only
            # (mcu_usb_arduino.md) — no motion, nothing safety-critical.
            "usb_arduino": cls.IO_ONLY,
            # Simulation target: accepts anything, drives nothing.
            "dummy": cls.POSITION,
        }.get((connection or "").strip().lower())
