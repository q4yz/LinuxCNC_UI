"""What one component or MCU router contributes to `machine.hal`.

Mappers never emit text. They return a :class:`HalFragment`, because
HAL is a netlist, not a document — `addf` order is functionally
meaningful (which thread runs a function first), and a signal a
component exports as a :class:`PinRequest` isn't real HAL until an MCU
router (a second, separate mapper) binds it to a physical pin. Text
assembly and ordering are the assembler's job
(`.agent/component/README.md` § 4), never a mapper's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .pin_models import ParsedPin

#: The two realtime threads a `.hal` file schedules functions into.
BASE_THREAD = "base-thread"
SERVO_THREAD = "servo-thread"


class PinRole(Enum):
    """What a requested pin is *for* — routers dispatch on this.

    A parport router treats STEP differently from DIR (only STEP gets
    `-out-reset`); a fieldbus router may not distinguish them at all.
    More roles land as later phases add components.
    """

    STEP = "step"
    DIR = "dir"
    ENABLE = "enable"
    ENDSTOP = "endstop"
    #: A command going out to a peripheral (spindle run/reverse/speed).
    #: Direction, not device — any I/O-only MCU can carry one.
    SPINDLE_OUT = "spindle_out"
    #: Feedback coming in from a peripheral (spindle speed/at-speed/health).
    SPINDLE_IN = "spindle_in"
    #: A duty/setpoint value going out to hardware (heater PID output,
    #: a referenced fan's commanded speed) — `remora.SP.N` on class B.
    ANALOG_OUT = "analog_out"
    #: A measured value coming in from hardware (a thermistor reading)
    #: — `remora.PV.N` on class B.
    ANALOG_IN = "analog_in"
    #: A generic digital output — direction, not device (same "any
    #: I/O-capable MCU can carry one" contract as SPINDLE_OUT). Used
    #: by the E-stop component's `out_pin` (`estop.md` § 3).
    DIGITAL_OUT = "digital_out"
    #: A generic digital input. Mechanically identical to ENDSTOP on
    #: every router today (a plain level read); kept as its own role
    #: rather than reusing ENDSTOP so a router's firmware-module
    #: naming (and a future validator rule) can tell "this is a home
    #: switch" from "this is some other digital input" apart. Used by
    #: the E-stop component's `fault_pin`.
    DIGITAL_IN = "digital_in"


@dataclass(frozen=True, slots=True)
class Addf:
    """One `addf <func> <thread>` line.

    ``order`` is the tie-break within one thread, per the role tiers
    README § 4 documents (base: read=0, make-pulses=1, write=2,
    reset=3; servo: read=0, motion=1, write=2) — never a raw line
    index, since two mappers contributing to the same thread don't
    know about each other's position.
    """

    func: str
    thread: str
    order: int = 0


@dataclass(frozen=True, slots=True)
class PinRequest:
    """"I need `signal` wired to a physical pin" — resolved in pass 2.

    ``owner`` is the requesting entity's id, kept only for diagnostics
    (a router that can't satisfy a request names who asked).
    """

    signal: str
    role: PinRole
    pin: ParsedPin
    owner: str


@dataclass(frozen=True, slots=True)
class FirmwareModuleRequest:
    """"This physical pin needs a firmware module entry" — a Remora-style
    board has no HAL pin to route at all; the pin only exists inside a
    `config.txt` sidecar the router assembles once per MCU. Kept
    parallel to :class:`PinRequest` rather than folded into it because
    it never becomes a `net` — routing it through the pin-router path
    would force every router to special-case "requests with nowhere to
    net".
    """

    mcu_id: str
    module: dict[str, object]


@dataclass
class HalFragment:
    """One component's (or one MCU router's) contribution.

    Every field is a flat list the assembler concatenates — ``addf``
    additionally gets globally sorted by ``(thread, order)`` since
    thread order is a cross-component invariant, not a per-fragment one.
    """

    loadrt: list[str] = field(default_factory=list)
    loadusr: list[str] = field(default_factory=list)
    addf: list[Addf] = field(default_factory=list)
    setp: list[str] = field(default_factory=list)
    nets: list[str] = field(default_factory=list)
    requests: list[PinRequest] = field(default_factory=list)
    firmware_modules: list[FirmwareModuleRequest] = field(default_factory=list)
    #: Sidecar files a router emits alongside HAL (Remora `config.txt`,
    #: EtherCAT slave XML, `vfd.ini`) — keyed by relative filename.
    files: dict[str, str] = field(default_factory=dict)

    def extend(self, other: "HalFragment") -> None:
        """Append every field of ``other`` onto ``self``, in place."""
        self.loadrt.extend(other.loadrt)
        self.loadusr.extend(other.loadusr)
        self.addf.extend(other.addf)
        self.setp.extend(other.setp)
        self.nets.extend(other.nets)
        self.requests.extend(other.requests)
        self.firmware_modules.extend(other.firmware_modules)
        self.files.update(other.files)


def combine(fragments: list[HalFragment]) -> HalFragment:
    """Concatenate ``fragments`` in order into one."""
    result = HalFragment()
    for fragment in fragments:
        result.extend(fragment)
    return result
