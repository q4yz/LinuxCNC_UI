"""Machine module package.

Re-exports the :func:`setup` factory that :class:`core.module_registry.ModuleRegistry`
imports when it walks ``backend/modules/*/`` at boot time. Modules
without a ``setup`` callable are skipped (and logged) by the registry.

Everything else (router, settings, jog endpoints, watchdog) lives in
sibling files inside this package. The split mirrors the discovery
layout described in :file:`MODULE_SYSTEM_ROADMAP.md` § 3::

    backend/modules/machine/
    ├── __init__.py        # this file
    ├── module.py          # MachineModule + setup() + on_load/on_unload
    ├── router.py          # state / mode / home / mdi endpoints
    ├── jog.py             # jog / keepalive / stop endpoints (no watchdog)
    ├── jog_watchdog.py    # 500 ms keep-alive safety watchdog
    ├── settings.py        # Pydantic MachineSettings defaults
    └── README.md          # human-facing module description

The 500 ms safety watchdog lives in its own file because it shares
module-private state with the jog router (``_active_jogs``) but
needs to start and stop independently of the request lifecycle.
Both files live in the same package so they can ``from . import jog``
without crossing boundaries.
"""
from .module import MachineModule, setup

__all__ = ["MachineModule", "setup"]
