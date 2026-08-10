"""Data model package for the ``machineconfig`` module.

Split into three files so the input graph, the LinuxCNC output
model, and the canonical ``hardware.json`` v2 shape are each
isolated:

* :mod:`.klipper_models` — the input-side graph produced by the
  strict parser from a Klipper ``.cfg``.
* :mod:`.linuxcnc_models` — the output-side model with
  :class:`~.linuxcnc_models.Axis` owning a
  :class:`list` of :class:`~.linuxcnc_models.Joint` objects.
* :mod:`.hardware_json_models` — the canonical ``hardware.json``
  v2 shape with flat ids and cross-reference validation.

The INI renderer (:mod:`backend.modules.machineconfig.compilers.ini_generator`)
consumes :class:`~.linuxcnc_models.Axis` and
:class:`~.linuxcnc_models.Joint`; the parser produces
:class:`~.klipper_models.MachineConfigGraph`. The bridge between the
two is :class:`~.linuxcnc_models.AxisBuilder`. The
hardware.json payload is produced by
:mod:`backend.modules.machineconfig.compilers.hardware_json_generator`
from the same parser output.
"""

from .hardware_json_models import (
    Axis as HardwareAxis,
    Driver as HardwareDriver,
    Endstop as HardwareEndstop,
    Fan as HardwareFan,
    HardwareJson,
    Heater as HardwareHeater,
    Stepper as HardwareStepper,
    TemperatureSensor,
    model_validate as validate_hardware_json,
    to_dict as hardware_json_to_dict,
)
from .klipper_models import (
    EndstopSwitch,
    Extruder,
    Fan,
    Heater,
    MachineConfig,
    MachineConfigGraph,
    MCU,
    Printer,
    Spindle,
    Stepper,
    TMC2209,
)
from .linuxcnc_models import (
    AXIS_ORDER,
    Axis,
    IniConfig,
    Joint,
    JointType,
)

__all__ = [
    "AXIS_ORDER",
    "Axis",
    "EndstopSwitch",
    "Extruder",
    "Fan",
    "HardwareAxis",
    "HardwareDriver",
    "HardwareEndstop",
    "HardwareFan",
    "HardwareHeater",
    "HardwareJson",
    "HardwareStepper",
    "Heater",
    "IniConfig",
    "Joint",
    "JointType",
    "MCU",
    "MachineConfig",
    "MachineConfigGraph",
    "Printer",
    "Spindle",
    "Stepper",
    "TemperatureSensor",
    "TMC2209",
    "hardware_json_to_dict",
    "validate_hardware_json",
]
