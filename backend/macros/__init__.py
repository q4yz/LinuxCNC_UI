"""Macros package — file-handling layer for ``.macro`` files.

Issue #87 scopes this package to file CRUD only; execution of macros
(G-code + Python blend) lives elsewhere and is out of scope. The
public surface is the :class:`MacroFileService` re-exported below so
callers can simply write ``from backend.macros import MacroFileService``
once a router mounts the service in a follow-up ticket.

The on-disk convention is:

* One file per macro, named ``<name>.macro``.
* Storage lives in a single directory (default
  ``backend/macros/``, configurable for tests via the constructor).
* The UI sees bare names (no suffix); the service re-attaches
  ``.macro`` internally so disk and API never disagree.

Security note (per the issue's security waiver): path traversal is
not defended against in this iteration. The next ticket that wires
this service to a router is expected to add input validation at the
HTTP boundary.
"""

from .service import MacroFileService, MacroNotFoundError

__all__ = ["MacroFileService", "MacroNotFoundError"]