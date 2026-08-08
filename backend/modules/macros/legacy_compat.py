"""Backward-compatibility shim for the legacy ``backend.macros`` package.

The macro CRUD implementation moved to
:mod:`backend.modules.macros.service` as part of the issue #90
relocation. This module re-exports the public API so any caller
that still does ``from backend.macros import MacroFileService``
(or imports this shim directly) keeps working during the
migration window. The legacy ``backend/macros/`` package can be
retired once all callers are migrated; this shim exists so the
transition is non-breaking.
"""

from .service import MACRO_SUFFIX, MacroFileService, MacroNotFoundError

__all__ = ["MACRO_SUFFIX", "MacroFileService", "MacroNotFoundError"]
