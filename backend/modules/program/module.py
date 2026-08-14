"""Program module — :class:`PluggableModule` implementation (stub).

This is the Phase 3a stub required by issue #38 § 6 Risk #7: the
program lifecycle endpoints live here so ``routers/machine.py``
can be deleted in this issue. The dedicated UI and the autonomous
program lifecycle are slated for Phase 3 proper — for now the
module exposes the HTTP surface only.

The module declares a typed settings surface so the canonical four
endpoints expose a non-empty payload from first boot; see
:mod:`backend.modules.program.settings`. ``settings_panel`` stays
``False`` for now because the Settings UI does not yet render the
program module — a future issue will flip it to ``True`` once the
frontend gains a settings tab for this module.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from core.protocols import (
    ModuleContext,
    ModuleManifest,
    PluggableModule,
    SidebarEntry,
)

from .router import router as _router
from .settings import ProgramSettings

logger = logging.getLogger("backend.modules.program")


_MANIFEST = ModuleManifest(
    id="program",
    title="Program",
    version="0.1.0",
    description="Program lifecycle (run / stop / pause / resume / parse).",
    sidebar=SidebarEntry(
        id="program",
        label="Program",
        icon="",
        order=80,
    ),
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

    def get_settings_model(self) -> BaseModel:
        """Return a fresh :class:`ProgramSettings` defaults instance.

        The contract requires every module to return a non-null
        Pydantic :class:`BaseModel`. Returning a typed model here
        seeds the per-module :class:`SettingsStore` so the four
        canonical settings endpoints expose a non-empty payload from
        first boot. See :mod:`backend.modules.program.settings`.
        """
        return ProgramSettings()


def setup() -> PluggableModule:
    """Factory consumed by :class:`ModuleRegistry.discover`."""
    return ProgramModule()


__all__ = ["ProgramModule", "setup", "ProgramSettings"]
