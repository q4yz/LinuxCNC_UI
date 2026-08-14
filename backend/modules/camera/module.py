"""Camera module — ``PluggableModule`` implementation.

This file is the entrypoint the registry imports via the package-level
``setup()`` factory. It owns:

* the static :class:`ModuleManifest` describing the module,
* the per-module :class:`CameraSettings` defaults passed to the
  registry's :class:`SettingsStore`,
* the lifecycle hooks :meth:`on_load` and :meth:`on_unload`.

The actual HTTP router lives in :mod:`backend.modules.camera.router`;
settings schema in :mod:`backend.modules.camera.settings`; USB camera
detection in :mod:`backend.modules.camera.detection`. Keeping these
concerns split mirrors the layout every module should follow (see
``MODULE_SYSTEM_ROADMAP.md`` § 3).

The module does **not** open any capture in ``on_load``. The
:class:`~router.UstreamerSupervisor` spawns ``ustreamer`` subprocesses
on-demand inside the ``/stream`` endpoint and terminates them on
shutdown. ``on_unload`` calls ``stop_manager()`` so any spawned child
is reaped before the lifespan ends.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter

from core.protocols import ModuleContext, ModuleManifest, PluggableModule, SidebarEntry

from .router import bind_settings_store, router as camera_router, stop_manager
from .settings import CameraSettings

logger = logging.getLogger("backend.modules.camera")


_MANIFEST = ModuleManifest(
    id="camera",
    title="Camera",
    version="0.3.0",
    description=(
        "Live USB webcam MJPEG stream via ustreamer with on-demand "
        "subprocess supervision (Issue #56)."
    ),
    sidebar=SidebarEntry(
        id="camera",
        label="Camera",
        icon="",
        order=50,
    ),
    settings_panel=True,
)


class CameraModule:
    """The :class:`PluggableModule` instance the registry boots."""

    manifest = _MANIFEST

    def __init__(self) -> None:
        # Share the module-level router with the settings registry —
        # the same router is mounted under ``/api/v1/modules/camera``
        # by ``ModuleRegistry._mount``.
        self._router: APIRouter = camera_router

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    def on_load(self, ctx: ModuleContext) -> None:
        """Wire the SettingsStore onto the supervisor.

        The first ``ustreamer`` subprocess is spawned lazily on the
        first ``/stream`` request, so this hook stays non-blocking and
        does not touch any external binary. The settings store is
        attached so the supervisor can re-read the configured
        ``default_device_id`` on every status request.
        """
        bind_settings_store(ctx.settings)
        logger.info("Camera module loaded.")

    def on_unload(self) -> None:
        """Terminate every spawned ustreamer subprocess.

        Idempotent — safe to call multiple times under
        ``uvicorn --reload``. The supervisor's ``shutdown()`` is
        tolerant of being torn down twice.
        """
        try:
            stop_manager()
        except Exception as exc:  # noqa: BLE001
            logger.error("CameraModule.on_unload: stop_manager raised %s", exc)
        logger.info("Camera module unloaded.")

    # ------------------------------------------------------------------ #
    # Registry hooks                                                     #
    # ------------------------------------------------------------------ #

    def get_router(self) -> APIRouter:
        """Return the module's HTTP router."""
        return self._router

    def get_settings_model(self) -> Optional[CameraSettings]:
        """Return the Pydantic defaults model for the settings store.

        The registry calls this before ``on_load`` and forwards the
        returned instance to ``SettingsStore(defaults=…)``. Modules
        without a typed schema simply return ``None`` and the store
        falls back to untyped JSON.
        """
        return CameraSettings()


def setup() -> PluggableModule:
    """Factory the registry imports via ``modules.camera.setup``."""
    return CameraModule()


__all__ = ["CameraModule", "setup"]