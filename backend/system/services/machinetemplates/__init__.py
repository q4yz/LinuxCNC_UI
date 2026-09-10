"""Machine template generation package.

This is the machine-config pipeline: a profile ``.cfg`` produces a
per-machine **template** set under ``machine_config/machines/<name>/configs/``
that an operator can hand-finish and deploy:

* ``machine.cfg``             — verbatim copy of the source profile (provenance).
* ``hardware.json``           — the real runtime contract.
* ``machine.ini``             — a LinuxCNC INI populated with known-good
  defaults plus every axis/joint section derived from ``hardware.json``
  (see :mod:`.ini_template_generator`).
* ``machine.hal``             — the full HAL pin catalog of the ``webgui``
  userspace component with per-pin connection suggestions.
* ``custom.hal``              — always loads the ``webgui`` HAL component
  and sources ``webgui_connections.hal``.
* ``webgui_connections.hal``  — seeded with real spindle/heater
  bindings; regenerated every time like every other file, with one
  exception — the currently-selected "main" machine can't be
  regenerated (and so can't lose this file's wiring) at all, see
  :class:`MainMachineProtectedError`.
* ``tool.tbl``                — minimal empty tool table so the
  generated INI's ``[EMCIO] TOOL_TABLE`` reference resolves.

The Remora ``config.txt`` flash payload and the pluggable-compiler
framework that used to live alongside this package have been
retired — see ``.agent/HANDOFF.md``.

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
    MainMachineProtectedError,
    generate_machine_templates,
    resolve_machine_configs_dir,
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
    "MainMachineProtectedError",
    "PinCatalog",
    "PinContainerDescriptor",
    "PinDescriptor",
    "build_pin_catalog",
    "generate_machine_templates",
    "render_hal_template",
    "render_ini_template",
    "resolve_machine_configs_dir",
]
