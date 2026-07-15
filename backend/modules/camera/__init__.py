"""Camera module — package entrypoint.

Re-exports the :func:`setup` factory that :class:`core.module_registry.ModuleRegistry`
imports when it walks ``backend/modules/*/`` at boot time. Modules
without a ``setup`` callable are skipped (and logged) by the registry.

Everything else (router, settings schema, manifest) lives in sibling
files inside this package. The split mirrors the discovery layout
described in ``MODULE_SYSTEM_ROADMAP.md`` § 3:

    backend/modules/camera/
    ├── __init__.py        # this file
    ├── module.py          # CameraModule + setup()
    ├── router.py          # HTTP endpoints + background frame worker
    ├── settings.py        # Pydantic CameraSettings defaults
    └── README.md          # human-facing module description
"""
from .module import CameraModule, setup

__all__ = ["CameraModule", "setup"]