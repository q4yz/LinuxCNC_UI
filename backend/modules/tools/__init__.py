"""Tools module package.

Re-exports the :func:`setup` factory so the
:class:`core.module_registry.ModuleRegistry` can discover this
module via ``backend.modules.tools.setup``.

The tools module exposes the operator-facing MDI command surface for
spindles and extruders (Issue #64). It owns:

* ``POST /api/v1/modules/tools/spindle`` — issue ``M3`` / ``M4`` /
  ``M5`` commands to start, reverse, or stop a spindle.
* ``POST /api/v1/modules/tools/extruder`` — drive an extruder axis
  in relative mode (``G91`` → ``G1 E{dist} F{speed}`` → ``G90``).

All hardware access goes through :func:`hardware.execute_sync_cmd`
so the module stays compatible with :mod:`hardware.linuxcnc_mock`.
The module does **not** publish telemetry on its own — actual
RPM / position numbers are still owned by the machine module's
telemetry loop. The frontend hard-codes a mock tool list today;
dynamic configuration is intentionally out of scope for this
issue.
"""

from .module import setup

__all__ = ["setup"]