"""State module package — read/set machine state, mode, and MDI.

Re-exports the :func:`setup` factory that
:class:`core.module_registry.ModuleRegistry` imports when it walks
``backend/modules/*/`` at boot time. Modules without a ``setup``
callable are skipped (and logged) by the registry.

This module split off from the historical ``axis`` (formerly
``machine``) module when the module router was reorganised:

    backend/modules/state/
    ├── __init__.py        # this file
    ├── module.py          # StateModule + setup() + on_load/on_unload
    ├── service.py         # StateService + MachineState facade
    └── router.py          # GET /state, POST /state, POST /mode, POST /mdi

The ``/home`` endpoint lives in :mod:`backend.modules.axis.router`
because homing is an axis-motion action; everything else
(state / mode / MDI) lives here because it operates on the machine's
overall task mode rather than on a specific axis.

The four endpoints are thin HTTP wrappers around the layer-2 facade
in :mod:`modules.state.service` (:class:`StateService`). The router
does not import the facade's class — only the singleton accessor —
so a refactor of the facade does not touch this file.
"""
from .module import StateModule, setup

__all__ = ["StateModule", "setup"]