"""Backward-compatibility shim for the legacy ``backend.macros`` package.

The macro CRUD implementation moved to
:mod:`backend.modules.macros.service` as part of the Issue #90
relocation. This shim re-exports the public API from the new
location so any caller that still does
``from backend.macros import MacroFileService`` keeps working
during the migration window.

The legacy ``backend/macros/service.py`` implementation is no
longer imported by this package. The legacy folder can be
retired by the orchestrator once all callers migrate to
:mod:`backend.modules.macros`.
"""

from backend.modules.macros.service import (
    MACRO_SUFFIX,
    MacroFileService,
    MacroNotFoundError,
)

__all__ = ["MACRO_SUFFIX", "MacroFileService", "MacroNotFoundError"]
