"""Shared machine-config generation helpers.

Historically this package also housed a pluggable compiler
framework (``Compiler`` / ``CompilerRegistry`` / the
``KlipperToLinuxCNCCompiler`` implementation, plus a Remora
``config.txt`` flash-payload generator) that translated a profile
into staged artifacts under ``machine_config/ready_for_deploy``.
That framework has been retired in favour of the template-based
generator in :mod:`services.machinetemplates` — see
``.agent/HANDOFF.md`` for the removal notes.

What's left here is genuinely shared, non-compiler-specific
generation logic that the template system depends on:

* :mod:`.axis_builder` — builds LinuxCNC ``Axis`` / ``Joint``
  objects from a parsed profile graph (handles multi-joint axes,
  e.g. a dual-motor gantry).
* :mod:`.heater_extractor` — extracts the heater/temperature-sensor
  list from a parsed graph.
* :mod:`.hardware_json_generator` — builds the canonical
  ``hardware.json`` payload from a parsed graph.
"""

from __future__ import annotations

from machineconfig_parser import derive_fan_name
from .axis_builder import AxisBuilder, AxisMappingPolicy, stepgen_scale
from .hardware_json_generator import build_hardware_json, write_hardware_json
from .heater_extractor import (
    HardwareHeater,
    HeaterExtractor,
    derive_heater_name,
)

__all__ = [
    "AxisBuilder",
    "AxisMappingPolicy",
    "HardwareHeater",
    "HeaterExtractor",
    "build_hardware_json",
    "derive_fan_name",
    "derive_heater_name",
    "stepgen_scale",
    "write_hardware_json",
]
