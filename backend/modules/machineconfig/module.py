"""Machineconfig module — :class:`PluggableModule` implementation.

The module is the new home for the Machine Configuration, Compilation,
and Deployment flow requested by issue #41. It owns:

* a clean object-oriented :class:`~.compilers.Compiler` framework,
* the file-system CRUD for ``machine_config/profiles`` (via
  :class:`services.ConfigFileService`),
* the read-only viewer endpoints for ``ready_for_deploy`` and ``active``
  (via :class:`services.StagedFileService` and
  :class:`services.ActiveFileService`),
* a deploy endpoint that accepts ``confirm_flash`` for Remora-style
  remote-controller workflows (the staged → active promotion lives
  in :meth:`services.StagedFileService.deploy_to_active`),
* a per-module settings surface (the canonical four routes are
  mounted by the registry; this module ships the Pydantic defaults
  via :class:`~.settings.MachineConfigSettings`).

Issue #49 replaced the legacy ``/api/v1/compiler/*`` flat-file
endpoints — they were superseded by this module and have been
deleted from the codebase. The frontend ``EditorView`` and
``ProfilesExplorer`` panels now consume the unified
``/api/v1/modules/machineconfig/*`` surface.
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

from services import (
    ActiveFileService,
    ConfigFileService,
    StagedFileService,
    get_active_service,
    get_config_service,
    get_staged_service,
)

from .compilers import autoload as autoload_compilers
from .router import router as _router
from .settings import MachineConfigSettings

logger = logging.getLogger("backend.modules.machineconfig")


# ``autoload`` is a no-op once the package has been imported; calling
# it again here is harmless because the registry's ``register`` is
# idempotent on id collisions. The explicit call documents the
# intent: by the time ``on_load`` runs, every concrete Compiler
# subclass in this package is registered.
autoload_compilers()


_MANIFEST = ModuleManifest(
    id="machineconfig",
    title="Machine Config",
    version="0.1.0",
    description="Profiles, compilation, staged/active viewer, deployment.",
    # Module owns a sidebar entry so the app's left rail picks it up.
    sidebar={"id": "machineconfig", "label": "Machine Config", "order": 60},
    settings_panel=True,
)


class MachineConfigModule:
    """The :class:`PluggableModule` instance the registry boots."""

    manifest = _MANIFEST

    def __init__(self) -> None:
        # Mount our router as the only router the registry needs to
        # see; settings endpoints are added by the registry itself.
        self._router: APIRouter = _router

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    def on_load(self, ctx: ModuleContext) -> None:
        """Make sure the three directories exist on disk.

        Boot is the only place we touch the filesystem because the
        FastAPI lifespan is single-threaded at boot; later endpoints
        are read-mostly and a missing directory is reported as a 404.
        """
        try:
            # The service constructors each ``mkdir(exist_ok=True)`` the
            # root they manage, so the three canonical directories are
            # materialised here without the router having to know.
            config_service: ConfigFileService = get_config_service()
            staged_service: StagedFileService = get_staged_service()
            active_service: ActiveFileService = get_active_service()
            logger.info(
                "machineconfig services ready: profiles=%s staged=%s active=%s",
                config_service.root,
                staged_service.root,
                active_service.root,
            )
        except OSError as exc:  # noqa: BLE001 - filesystem errors are non-fatal
            logger.warning("machineconfig: cannot ensure directories: %s", exc)

    def on_unload(self) -> None:
        """No background work; the directories persist across reloads."""
        logger.debug("machineconfig module unloaded (no background work)")

    # ------------------------------------------------------------------ #
    # Registry hooks                                                     #
    # ------------------------------------------------------------------ #

    def get_router(self) -> APIRouter:
        """Return the machineconfig HTTP router.

        The registry mounts it at
        ``/api/v1/modules/machineconfig`` with OpenAPI tag
        ``modules:machineconfig``.
        """
        return self._router

    def get_settings_model(self) -> Optional[BaseModel]:
        """Return a fresh :class:`MachineConfigSettings` defaults model.

        Settings are validated through the registry's
        :class:`core.settings_store.SettingsStore`; the four canonical
        endpoints (``GET/PUT`` bulk, ``GET/PUT`` per-key) are mounted
        at ``/api/v1/modules/machineconfig/settings``.
        """
        return MachineConfigSettings()


def setup() -> PluggableModule:
    """Factory consumed by :class:`ModuleRegistry.discover`."""
    return MachineConfigModule()


__all__ = ["MachineConfigModule", "setup"]