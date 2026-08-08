"""Macros module package (issue #92, parser: issue #95).

Owns the storage and retrieval of custom ``.macro`` files (raw text
payloads eventually executed as a mix of G-code + Python). The HTTP
surface is intentionally read-write — list / read / create / update
/ delete — and is mounted by :class:`core.module_registry.ModuleRegistry`
under ``/api/v1/modules/macros``.

Issue #92 covers **file handling only** — the storage layer and the
HTTP router. Issue #95 adds a **pure-Python parser** that splits the
raw text payload (as returned by :meth:`MacroStorage.read`) into an
ordered list of alternating ``static`` and ``python`` blocks. The
parser is library-only: no HTTP endpoint, no execution. The future
Interpreter module consumes the structured output.

Re-exports :func:`setup` so the registry can discover the module via
``backend.modules.macros.setup`` (the package name is the candidate
id; ``manifest.id`` is the public identifier). Also re-exports
:func:`parse_macro`, :class:`Block`, and :class:`MacroParseError` so
the future Interpreter module can import them as
``from backend.modules.macros import parse_macro``.
"""

from .module import setup
from .parser import Block, MacroParseError, parse_macro

__all__ = [
    "setup",
    "parse_macro",
    "Block",
    "MacroParseError",
]
