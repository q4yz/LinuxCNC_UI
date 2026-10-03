"""The UI's MCU reset -> `webgui_connections.hal`.

`McuService.reset_mcus()` (machine backend) pulses
``webgui.<mcu_id>-reset`` True -> False for every resettable MCU (a
Remora board that declared a ``reset_pin``). This binds that pin to
the Remora driver's ``PRU-reset`` input — a plain passthrough net, the
same shape as the E-stop binding (`EstopWebguiMapper`).

Which MCUs qualify and the pin's name come from the runtime's own
`McuMapper`, so the compiler can never net a ``webgui.*`` pin the
runtime does not register (a HAL load error).
"""

from __future__ import annotations

from typing import Any

from mappers.mcu.McuMapper import McuMapper


class McuResetWebguiMapper:
    """`net` line binding `webgui.<id>-reset` onto `remora.PRU-reset`."""

    @staticmethod
    def to_lines(mcu: dict[str, Any]) -> list[str]:
        if not McuMapper.is_resettable(mcu):
            return []
        signal = McuMapper.reset_pin_name(str(mcu["id"]))
        return [
            f"# MCU reset ({mcu['id']})",
            f"net {signal} webgui.{signal} => remora.PRU-reset",
            "",
        ]


__all__ = ["McuResetWebguiMapper"]
