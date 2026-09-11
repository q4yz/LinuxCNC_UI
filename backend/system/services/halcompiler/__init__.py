"""HAL compiler: hardware.json -> a functional ``machine.hal``.

:mod:`.validator` answers "can this machine be compiled, and if not,
why not" (Phase 0 — no emission). :func:`.compile_machine_hal` is the
emitter: it assembles every component/MCU mapper's contribution and
renders the result. **Callers must validate first** — the assembler
trusts a zero-error payload and does not re-check referential or
motion-class rules.

Phase 1 covers class A (step/dir realtime, parallel port); Phase 2
adds class B (position-command, Remora SPI). A
:class:`.assembler.UnsupportedMcuError` on any other MCU connection
type — including ``remora-eth``, still unrouted — is the honest "not
implemented yet" rather than silently wrong output. Component specs
live in ``.agent/component/``.
"""

from mappers.machineconfig import PinStringMapper

from .assembler import HalAssembler, UnsupportedMcuError, assemble_machine
from .components.EstopWebguiMapper import EstopWebguiMapper
from .components.FanWebguiMapper import FanWebguiMapper
from .components.HeaterWebguiMapper import HeaterWebguiMapper
from .components.SpindleWebguiMapper import SpindleWebguiMapper
from .renderer import render_hal
from .validator import MachineValidator, validate_machine


def compile_machine_hal(payload: dict[str, object]) -> str:
    """Validate, then assemble and render — the one-call happy path.

    Raises :class:`ValueError` (with every diagnostic's text) if the
    payload has any error-level finding; warnings do not block.
    """
    diagnostics = validate_machine(payload)
    if MachineValidator.has_errors(diagnostics):
        details = "\n".join(str(d) for d in diagnostics if d.is_error)
        raise ValueError(f"machine does not compile:\n{details}")
    return render_hal(assemble_machine(payload))


def render_webgui_connections(payload: dict[str, object]) -> str:
    """Estop/spindle/heater/fan UI bindings — `net` lines for a fresh
    ``webgui_connections.hal``, not ``machine.hal``.

    Used only to *seed* a machine's ``webgui_connections.hal`` the
    first time it's generated — ``generate_machine_templates``
    preserves hand edits on every regenerate after that, so this
    never overwrites an operator's own wiring (see
    ``SpindleWebguiMapper``/``HeaterWebguiMapper``/``EstopWebguiMapper``/
    ``FanWebguiMapper`` for why the pin names have to match the
    runtime's own convention exactly).

    Deliberately independent of :func:`compile_machine_hal` /
    :func:`validate_machine` — a spindle or heater with a real pin
    still deserves a working UI binding even if some unrelated part
    of the machine doesn't validate yet. No estop and no spindle/heater/
    fan entities (a payload predating one of these requirements, or a
    bare test fixture) returns an empty string.

    A ``kind: "heater"`` fan gets no binding at all — never operator/
    G-code commandable, see `.agent/component/fan.md`. Neither does a
    ``kind: "part"`` fan whose pin sits in ``duplicate_pin_overrides``
    (the heater/fan-shares-a-pin case `hardware_json_generator`
    auto-populates that list for, or an operator's own explicit
    entry): `HalAssembler` renames that fan's signal onto whatever
    else already claims the physical pin, so a standalone
    ``webgui.<fan_id>`` binding here would land on a signal name
    `machine.hal` never actually uses — silently disconnected from
    the real output, not a working control surface.
    """
    duplicate_pin_overrides = {
        str(p) for p in (payload.get("duplicate_pin_overrides") or [])
    }

    def _fan_pin_is_shared(fan: dict[str, object]) -> bool:
        pin = fan.get("pin")
        if not pin:
            return False
        try:
            return PinStringMapper.from_string(str(pin)).qualified in duplicate_pin_overrides
        except ValueError:
            return False

    lines: list[str] = []
    if isinstance(payload.get("estop"), dict):
        lines.extend(EstopWebguiMapper.to_lines())
    for tool in payload.get("tools", []) or []:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "spindle_digital":
            lines.extend(SpindleWebguiMapper.to_lines(tool))
        elif tool.get("type") in ("extruder", "heated_bed"):
            lines.extend(HeaterWebguiMapper.to_lines(tool))
    for fan in payload.get("fans", []) or []:
        if not isinstance(fan, dict):
            continue
        if fan.get("kind", "part") == "part" and not _fan_pin_is_shared(fan):
            lines.extend(FanWebguiMapper.to_lines(fan))
    if not lines:
        return ""
    return "\n".join(lines).rstrip("\n") + "\n"


__all__ = [
    "HalAssembler",
    "MachineValidator",
    "UnsupportedMcuError",
    "assemble_machine",
    "compile_machine_hal",
    "render_hal",
    "render_webgui_connections",
    "validate_machine",
]
