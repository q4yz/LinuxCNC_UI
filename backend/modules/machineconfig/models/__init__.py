"""Data model package for the ``machineconfig`` module.

Split into two files so the one-to-many axis-to-joint relationship
required by LinuxCNC is explicit:

* :mod:`.klipper_models` — the input-side graph produced by the
  strict parser from a Klipper ``.cfg``.
* :mod:`.linuxcnc_models` — the output-side model with
  :class:`~.linuxcnc_models.Axis` owning a
  :class:`list` of :class:`~.linuxcnc_models.Joint` objects.

The INI renderer (:mod:`backend.modules.machineconfig.compilers.ini_generator`)
consumes :class:`~.linuxcnc_models.Axis` and
:class:`~.linuxcnc_models.Joint`; the parser produces
:class:`~.klipper_models.MachineConfigGraph`. The bridge between the
two is :class:`~.linuxcnc_models.AxisBuilder`.
"""

from .klipper_models import (
    EndstopSwitch,
    Extruder,
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
    "TMC2209",
]
