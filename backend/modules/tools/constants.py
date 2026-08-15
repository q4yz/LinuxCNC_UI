"""Tools module — shared constants.

The MDI templates and the canonical ``halui.spindle.override.scale``
pin name are referenced by both :class:`ToolsService` (for
extruder dispatch) and :class:`SpindleService` (for spindle
dispatch). Putting them in a leaf module breaks the circular
import that would otherwise appear when
``spindle_digital_service.py`` imports from ``tool_service.py`` and vice
versa.
"""

from __future__ import annotations

from enum import Enum

# Canonical LinuxCNC MDI strings. Kept module-private so the
# service functions stay readable. Re-exported through
# :mod:`modules.tools.tool_service.__all__` for unit tests that
# want to assert the exact strings the endpoint emits.
M3_FORWARD = "M3 S{speed}"
M4_BACKWARD = "M4 S{speed}"
M5_STOP = "M5"
G91_RELATIVE = "G91"
G90_ABSOLUTE = "G90"
G1_EXTRUDE = "G1 E{dist} F{speed}"


# Canonical LinuxCNC HAL pin for the relative spindle-override.
# ``halui.spindle.override.scale`` accepts values in the
# ``[0.0, 2.0]`` range — ``1.0`` is the operator-default 100%.
DEFAULT_SPINDLE_OVERRIDE_PIN = "halui.spindle.override.scale"


__all__ = [
    "DEFAULT_SPINDLE_OVERRIDE_PIN",
    "G1_EXTRUDE",
    "G90_ABSOLUTE",
    "G91_RELATIVE",
    "M3_FORWARD",
    "M4_BACKWARD",
    "M5_STOP",
]


class ToolType(str, Enum):
    """Supported hardware tool types in hardware.json."""
    SPINDLE_DIGITAL = "spindle_digital"
    SPINDLE_ANALOG = "spindle_analog"
    EXTRUDER = "extruder"
    HEATED_BED = "heated_bed"