"""Data model package for the ``machineconfig`` module.

Split into three files so the input graph, the LinuxCNC output
model, and the canonical ``hardware.json`` v2 shape are each
isolated:

* :mod:`.KlipperModels` — the input-side graph produced by the
  strict parser from a Klipper ``.cfg``.
* :mod:`.LinuxCNCModels` — the output-side model with
  :class:`~.LinuxCNCModels.Axis` owning a
  :class:`list` of :class:`~.LinuxCNCModels.Joint` objects.
* :mod:`.HardwareJsonModels` — the canonical ``hardware.json``
  v2 shape with flat ids and cross-reference validation.

The INI renderer (:mod:`backend.services.machineconfig.ini_generator`)
consumes :class:`~.LinuxCNCModels.Axis` and
:class:`~.LinuxCNCModels.Joint`; the parser produces
:class:`~.KlipperModels.MachineConfigGraph`. The bridge between the
two is :class:`~.LinuxCNCModels.AxisBuilder`. The
hardware.json payload is produced by
:mod:`backend.services.machineconfig.hardware_json_generator`
from the same parser output.
"""

from .HardwareJsonModels import (
    Axis as HardwareAxis,
    Driver as HardwareDriver,
    Endstop as HardwareEndstop,
    Estop as HardwareEstop,
    Fan as HardwareFan,
    HardwareJson,
    Probe as HardwareProbe,
    Stepper as HardwareStepper,
    TemperatureSensor,
    Tool as HardwareTool,
    model_validate as validate_hardware_json,
    to_dict as hardware_json_to_dict,
)
from .KlipperModels import (
    ConnectionType,
    EndstopSwitch,
    Estop,
    Extruder,
    Fan,
    Heater,
    HeaterFan,
    MachineConfig,
    MachineConfigGraph,
    MCU,
    Printer,
    Probe,
    SpindleAnalog,
    SpindleDigital,
    Stepper,
    TMC2209,
    connection_to_hal_type,
)
from .LinuxCNCModels import (
    AXIS_ORDER,
    Axis,
    IniConfig,
    Joint,
    JointType,
)

__all__ = [
    "AXIS_ORDER",
    "Axis",
    "ConnectionType",
    "EndstopSwitch",
    "Estop",
    "Extruder",
    "Fan",
    "HardwareAxis",
    "HardwareDriver",
    "HardwareEndstop",
    "HardwareEstop",
    "HardwareFan",
    "HardwareJson",
    "HardwareProbe",
    "HardwareStepper",
    "HardwareTool",
    "Heater",
    "HeaterFan",
    "IniConfig",
    "Joint",
    "JointType",
    "MCU",
    "MachineConfig",
    "MachineConfigGraph",
    "Printer",
    "Probe",
    "SpindleAnalog",
    "SpindleDigital",
    "Stepper",
    "TemperatureSensor",
    "TMC2209",
    "connection_to_hal_type",
    "hardware_json_to_dict",
    "validate_hardware_json",
]
