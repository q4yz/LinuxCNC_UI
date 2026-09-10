"""STM32 GPIO name -> the underscored spelling Remora's `config.txt` expects.

Klipper (and this project's `.cfg` grammar) writes STM32 pins without a
separator — `PF13`, `PA0`. Remora's firmware config uses an underscore
between the port letter and the pin number — `PF_13`, `PA_0` — see the
real, working reference at `machine_config/example/ender3/config.txt`
(every `"Pin"`/`"Step Pin"`/`"RX pin"` value there is underscored).
Getting this wrong doesn't fail loudly: `ArduinoJSON` just won't match
the pin name against the board's pin table, so the module silently
never initialises.

Only used building `config.txt` firmware modules — never in `.hal`
text, which doesn't care about hardware pin-naming conventions at all.
"""

from __future__ import annotations

import re

_STM32_PIN = re.compile(r"^(P[A-Za-z])(\d+)$")


class RemoraFirmwarePinMapper:
    """Converts one pin id to Remora's `config.txt` spelling."""

    @staticmethod
    def to_firmware_pin(pin_id: str) -> str:
        """`"PF13"` -> `"PF_13"`. Anything not matching that shape
        (already underscored, or not an STM32 port pin at all) is
        returned unchanged rather than mangled — a router that hands
        this a non-STM32 pin id has bigger problems than formatting."""
        match = _STM32_PIN.match(pin_id)
        if not match:
            return pin_id
        port, number = match.groups()
        return f"{port}_{number}"


__all__ = ["RemoraFirmwarePinMapper"]
