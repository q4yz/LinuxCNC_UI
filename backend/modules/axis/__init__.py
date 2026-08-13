"""Axis module package.

Re-exports the :func:`setup` factory that :class:`core.module_registry.ModuleRegistry`
imports when it walks ``backend/modules/*/`` at boot time. Modules
without a ``setup`` callable are skipped (and logged) by the registry.

The split mirrors the discovery layout described in :file:`MODULE_SYSTEM_ROADMAP.md` § 3::

    backend/modules/axis/
    ├── __init__.py        # this file
    ├── module.py          # AxisModule + setup() + on_load/on_unload
    ├── service.py         # AxisService (homing facade)
    ├── router.py          # POST /home (axis-motion action)
    ├── jog.py             # WS-dispatch helpers + _active_jogs state
    ├── jog_watchdog.py    # 500 ms keep-alive safety watchdog
    └── settings.py        # Pydantic MachineSettings defaults

The 500 ms safety watchdog lives in its own file because it shares
module-private state with the jog helpers (``_active_jogs``) but
needs to start and stop independently of the request lifecycle.
Both files live in the same package so they can ``from . import jog``
without crossing boundaries.

The ``POST /home`` endpoint lives here because homing is an
axis-motion action (similar in nature to jog dispatch). The state /
mode / MDI endpoints live in :mod:`backend.modules.state.router`;
the two routers each call into their own dedicated service
singleton (:class:`AxisService` and :class:`StateService`).
"""
from .module import AxisModule, setup

__all__ = ["AxisModule", "setup"]