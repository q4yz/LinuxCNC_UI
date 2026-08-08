"""Macros module package (issue #92).

Owns the storage and retrieval of custom ``.macro`` files (raw text
payloads eventually executed as a mix of G-code + Python). The HTTP
surface is intentionally read-write — list / read / create / update
/ delete — and is mounted by :class:`core.module_registry.ModuleRegistry`
under ``/api/v1/modules/macros``.

This ticket covers **file handling only**. The frontend Activation
list view and Editor view land in a later ticket; the storage and
HTTP layers are deliberately decoupled so the upcoming UI work can
swap implementations without rewriting this module.

Re-exports :func:`setup` so the registry can discover the module via
``backend.modules.macros.setup`` (the package name is the candidate
id; ``manifest.id`` is the public identifier).
"""

from .module import setup

__all__ = ["setup"]
