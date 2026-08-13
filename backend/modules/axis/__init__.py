"""Axis module package.

Re-exports the :func:`setup` factory that :class:`core.module_registry.ModuleRegistry`
imports when it walks ``backend/modules/*/`` at boot time. Modules
without a ``setup`` callable are skipped (and logged) by the registry.

The split mirrors the discovery layout described in :file:`MODULE_SYSTEM_ROADMAP.md` § 3::

    backend/modules/axis/
    ├── __init__.py        # this file
    ├── module.py          # AxisModule + setup() + on_load/on_unload
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
both routers call into the shared layer-2 facade
:class:`MachineControlService` from :mod:`backend.services.machine_service`.

The previous ``machine`` module split Service / Adapter / Facade
responsibility across three sibling files — those are gone. The
``backend.modules.axis`` is jog + home dispatch, and the
hardware-folder facade is :mod:`backend.services.machine_service`.
"""
from .module import AxisModule, setup

__all__ = ["AxisModule", "setup"]