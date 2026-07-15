"""Camera module — ``PluggableModule`` implementation.

This file is the entrypoint the registry imports via the package-level
``setup()`` factory. It owns:

* the static :class:`ModuleManifest` describing the module,
* the per-module :class:`CameraSettings` defaults passed to the
  registry's :class:`SettingsStore`,
* the lifecycle hooks :meth:`on_load` and :meth:`on_unload`.

The actual HTTP router lives in :mod:`backend.modules.camera.router`;
settings schema in :mod:`backend.modules.camera.settings`. Keeping
these three concerns split mirrors the layout every module should
follow (see ``MODULE_SYSTEM_ROADMAP.md`` § 3).

The module does **not** start the OpenCV capture in ``on_load``. The
worker is started lazily by the ``/stream`` endpoint on first request
so a deployment that never serves the camera (e.g. headless CI) does
not waste an OpenCV handle. ``on_unload`` still stops the worker so a
shutdown is clean.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter

from core.protocols import ModuleContext, ModuleManifest, PluggableModule

from .router import bind_worker_settings, router as camera_router, stop_worker
from .settings import CameraSettings

logger = logging.getLogger("backend.modules.camera")


_MANIFEST = ModuleManifest(
    id="camera",
    title="Camera",
    version="0.1.0",
    description="Live USB webcam MJPEG stream.",
    sidebar=None,
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
        """Wire the SettingsStore onto the worker.

        The worker is started lazily on first stream request, so this
        hook stays non-blocking and does not touch the OpenCV install.
        The settings store is attached so the worker can re-read its
        configuration on every frame.
        """
        bind_worker_settings(ctx.settings)
        logger.info("Camera module loaded.")

    def on_unload(self) -> None:
        """Stop the worker and release OpenCV handles.

        Idempotent — safe to call multiple times under
        ``uvicorn --reload``. The worker also tolerates being torn
        down twice because ``stop()`` guards each of its members.
        """
        try:
            stop_worker()
        except Exception as exc:  # noqa: BLE001
            logger.error("CameraModule.on_unload: stop_worker raised %s", exc)
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