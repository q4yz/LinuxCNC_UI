"""What an ``[input_pin NAME]`` edge does: a halui MDI command
(``<edge>_ngc``) or setting an output (``<edge>_halpin_set``). Built by
:class:`InputPinHalMapper`, read by the HAL mappers and the INI renderer."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MdiCommand:
    """One ``[HALUI] MDI_COMMAND`` — ``halui.mdi-command-<index>``."""

    index: int
    input_id: str
    edge: str  # "rising" | "falling"
    subroutine: str
    gcode: str

    @property
    def ini_line(self) -> str:
        return f"MDI_COMMAND = o<{self.subroutine}> call"

    @property
    def file_name(self) -> str:
        return f"{self.subroutine}.ngc"

    @property
    def file_content(self) -> str:
        return (
            f"o<{self.subroutine}> sub\n{self.gcode}\no<{self.subroutine}> endsub\nM2\n"
        )


@dataclass(frozen=True, slots=True)
class HalpinSetAction:
    """``<edge>_halpin_set: <output>, <value>`` of one input."""

    input_id: str
    edge: str  # "rising" | "falling"
    output_id: str
    value: float

    @property
    def pulse(self) -> str:
        """The one-period signal of this input edge (`InputPinHalMapper`)."""
        return f"{self.input_id}-{self.edge}"


__all__ = ["HalpinSetAction", "MdiCommand"]
