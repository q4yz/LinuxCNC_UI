"""Macros module public entrypoint."""

from .module import MacrosModule, setup
from .service import MACRO_SUFFIX, MacroFileService, MacroNotFoundError

__all__ = [
    "MACRO_SUFFIX",
    "MacroFileService",
    "MacroNotFoundError",
    "MacrosModule",
    "setup",
]
