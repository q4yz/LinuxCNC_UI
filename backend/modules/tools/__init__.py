"""Tools module package.

Re-exports the :func:`setup` factory so the
:class:`core.module_registry.ModuleRegistry` can discover this
module via ``backend.modules.tools.setup``.

The tools module owns the operator-facing MDI and target-setting
surface. It exposes three endpoints, mounted under
``/api/v1/modules/tools``:

* ``POST /tools/{id}/target`` — set the target temperature for a
  heating tool by dispatching ``set_temperature`` on the tool's
  ``sensor`` reference.
* ``POST /spindle`` — issue ``M3`` / ``M4`` / ``M5`` to start,
  reverse, or stop a spindle.
* ``POST /extruder`` — drive an extruder axis in relative mode
  (``G91`` → ``G1 E{dist} F{speed}`` → ``G90``).

The historical ``GET /tools`` listing endpoint was superseded
by the base-thread snapshot
(``GET /api/v1/base-thread/snapshot``) which now carries the
tool list alongside progress and sensors in a single 1 Hz
round-trip. Tool reads now go through
:func:`modules.tools.service.collect_tools`.

All hardware access goes through :func:`hardware.execute_sync_cmd`
so the module stays compatible with the unified
:mod:`hardware.connection` surface (real LinuxCNC + in-memory mock).
The module is fire-and-forget for MDI commands — there is no
event-bus publication.
"""

from .module import setup

__all__ = ["setup"]