"""Machine template generation package.

This package is the *replacement* for the ambitious Klipper compiler:
instead of translating a profile into a fully wired LinuxCNC
configuration it emits a per-machine **template** set that an operator
finishes by hand:

* ``machine.cfg``   — verbatim copy of the source profile (provenance).
* ``hardware.json`` — the real runtime contract, produced by the same
  generator the (now deprecated) compiler used.
* ``machine.ini``   — a LinuxCNC INI skeleton (placeholders, not runable).
* ``machine.hal``   — the full HAL pin catalog of the ``webgui``
  userspace component with per-pin connection suggestions.

Remora flash payload (``config.txt``) is intentionally NOT generated.

The HAL pin catalog is sourced from the preloaded services
(:func:`ToolsService.get_halpins` / :func:`TemperatureService.get_halpins`
/ :func:`StateService.get_halpins`); by contract no pins are ever added
at runtime, so the catalog is a stable snapshot of the ``webgui``
component surface.
"""

from __future__ import annotations

from .generator import (
    GENERATED_FILES,
    GenerateResult,
    MachineExistsError,
    generate_machine_templates,
)
from .hal_template_generator import render_hal_template
from .ini_template_generator import render_ini_template
from .pin_catalog import (
    PinCatalog,
    PinContainerDescriptor,
    PinDescriptor,
    build_pin_catalog,
)

__all__ = [
    "GENERATED_FILES",
    "GenerateResult",
    "MachineExistsError",
    "PinCatalog",
    "PinContainerDescriptor",
    "PinDescriptor",
    "build_pin_catalog",
    "generate_machine_templates",
    "render_hal_template",
    "render_ini_template",
]
