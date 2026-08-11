"""Tools module package.

Re-exports the :func:`setup` factory so the
:class:`core.module_registry.ModuleRegistry` can discover this
module via ``backend.modules.tools.setup``.

The tools module owns the operator-facing tool surface. It
exposes four endpoints, mounted under
``/api/v1/modules/tools``:

* ``GET  /tools`` — list every tool the active ``hardware.json``
  ``tools[]`` declares, overlaid with runtime state (actual /
  target temperature for heating tools, actual RPM for digital
  spindles). The ToolPanel polls this every second.
* ``POST /tools/{id}/target`` — set the target temperature for a
  heating tool by dispatching ``set_temperature`` on the tool's
  ``sensor`` reference.
* ``POST /spindle`` — issue ``M3`` / ``M4`` / ``M5`` to start,
  reverse, or stop a spindle.
* ``POST /extruder`` — drive an extruder axis in relative mode
  (``G91`` → ``G1 E{dist} F{speed}`` → ``G90``).

All hardware access goes through :func:`hardware.execute_sync_cmd`
so the module stays compatible with :mod:`hardware.linuxcnc_mock`.
The module is poll-based — there is no event-bus publication; the
frontend ``toolStore.start()`` polls the ``GET /tools`` endpoint
and the ``state.tools`` event-bus topic is reserved for a future
"recompile pushed" signal.
"""

from .module import setup

__all__ = ["setup"]