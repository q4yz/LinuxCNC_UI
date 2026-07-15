"""Temperature module package.

Re-exports the :func:`setup` factory so the :class:`ModuleRegistry`
can discover this module via ``backend.modules.temperature.setup``.

The temperature module owns:

* ``GET /api/v1/modules/temperature/sensors`` — return the current
  sensors dictionary (read-through of the hardware layer).
* ``POST /api/v1/modules/temperature/sensors/{name}/target`` —
  dispatch a ``set_temperature`` command to the hardware layer.
* Four canonical settings endpoints mounted by the registry under
  ``/api/v1/modules/temperature/settings`` (see
  :class:`core.module_registry.ModuleRegistry._build_default_settings_router`).

Mock simulation (``_temp_simulation_loop``) deliberately stays in
:mod:`hardware.linuxcnc_mock` per the audit's recommendation: the
simulation is process-wide, not module-scoped.
"""

from .module import setup

__all__ = ["setup"]
