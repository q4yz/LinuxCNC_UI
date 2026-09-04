from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class LinuxCNCError(BaseModel):
    """Single entry in the LinuxCNC error channel history.

    The backend feeds these into ``ServoThreadStateDTO.errors`` so the
    UI receives a consistent shape regardless of whether the source
    was the mock (``{kind, text, time}``) or a real LinuxCNC daemon
    (whose ``stat.errors`` exposes bare strings without a ``kind``
    field — the mapper wraps those into this shape).

    ``kind`` is the raw LinuxCNC NML error-class integer. The frontend
    keeps a translation table at ``frontend/src/core/linuxcnc-errors.ts``
    so operators see a human-readable name; the integer is *also*
    shipped so a power-user can grep the LinuxCNC source for the
    specific code.

    ``time`` is an ISO-8601 string. Empty when the upstream source did
    not stamp one (real LinuxCNC populates ``stat.errors`` without a
    timestamp).
    """

    kind: int = Field(default=0, description="LinuxCNC NML error class (kind)")
    text: str = Field(default="", description="Human-readable error text from the daemon")
    time: Optional[str] = Field(default=None, description="ISO-8601 timestamp; empty when unknown")


def now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string.

    Centralised so tests can monkey-patch a single helper to freeze
    time instead of mocking ``datetime`` everywhere.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
