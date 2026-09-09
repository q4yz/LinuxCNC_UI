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

from .assembler import HalAssembler, UnsupportedMcuError, assemble_machine
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


__all__ = [
    "HalAssembler",
    "MachineValidator",
    "UnsupportedMcuError",
    "assemble_machine",
    "compile_machine_hal",
    "render_hal",
    "validate_machine",
]
