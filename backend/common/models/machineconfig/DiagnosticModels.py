"""One problem found while checking a machine for compilability.

Diagnostics are *collected*, not raised. A config with six problems
should report six — the operator fixes them in one pass instead of
recompiling to discover the next one. That mirrors how the parser's
``ConfigValidationError`` hierarchy already carries a ``kind``
discriminator for the HTTP layer, except a validator run returns a
list rather than stopping at the first fault.

Codes are the ``E_*`` / ``W_*`` identifiers defined in
``.agent/component/README.md`` § 3 and in each component template's
routing section.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    #: The machine cannot be compiled until this is fixed.
    ERROR = "error"
    #: Compiles, but the result is probably not what was intended.
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A single finding, addressed to the operator.

    ``where`` is the entity the problem belongs to (``"stepper_x"``,
    ``"heater_bed"``) so the UI can point at a row rather than making
    the operator search a file.
    """

    code: str
    severity: Severity
    message: str
    where: str | None = None

    @property
    def is_error(self) -> bool:
        return self.severity is Severity.ERROR

    def __str__(self) -> str:
        location = f" [{self.where}]" if self.where else ""
        return f"{self.severity.value.upper()} {self.code}{location}: {self.message}"
