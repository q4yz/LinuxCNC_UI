"""Program module — :class:`PluggableModule` implementation (stub).

This is the Phase 3a stub required by issue #38 § 6 Risk #7: the
program lifecycle endpoints live here so ``routers/machine.py``
can be deleted in this issue. The dedicated UI and the autonomous
program lifecycle are slated for Phase 3 proper — for now the
module exposes the HTTP surface only.

Why is there no separate settings schema yet? The endpoints do not
read any settings, and inventing a schema just to populate the
settings tab would amount to dead UI. The manifest keeps
``settings_panel=False`` so the Settings view does not render an
empty tab. A later issue will add ``settings_panel=True`` once the
schema has real keys.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from core.protocols import (
    ModuleContext,
    ModuleManifest,
    PluggableModule,
)

from .router import router as _router

logger = logging.getLogger("backend.modules.program")


_MANIFEST = ModuleManifest(
    id="program",
    title="Program",
    version="0.1.0",
    description="Program lifecycle (run / stop / pause / resume / parse).",
    sidebar=None,
    settings_panel=False,
)


class ProgramModule:
    """The :class:`PluggableModule` instance the registry boots."""

    manifest = _MANIFEST

    def on_load(self, ctx: ModuleContext) -> None:  # noqa: D401
        """No-op: the HTTP surface mounts at boot; no background work."""
        logger.debug("program module on_load (no background work)")

    def on_unload(self) -> None:
        """No-op: on_load was a no-op."""
        logger.debug("program module on_unload (no-op)")

    def get_router(self) -> APIRouter:
        """Return the program HTTP router.

        Mounted by the registry at ``/api/v1/modules/program``.
        """
        return _router

    def get_settings_model(self) -> Optional[BaseModel]:
        """Return ``None`` — the program module has no settings schema.

        Returning ``None`` is the documented contract for modules
        without a Pydantic defaults model; the registry falls back
        to untyped JSON and exposes the four canonical settings
        endpoints anyway. The :class:`PluggableModule` protocol
        requires this method to exist even when the module has
        nothing to declare — the runtime check
        ``isinstance(obj, PluggableModule)`` looks for the method
        by name.
        """
        return None


def setup() -> PluggableModule:
    """Factory consumed by :class:`ModuleRegistry.discover`."""
    return ProgramModule()


__all__ = ["ProgramModule", "setup"]
