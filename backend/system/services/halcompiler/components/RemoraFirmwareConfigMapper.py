"""One Remora MCU's collected firmware modules -> its `config.txt` shape.

Pulled out of `HalAssembler._render_firmware_configs`, which used to
build this dict inline — the assembler's own job is aggregating
*which* modules belong to *which* MCU (`.agent/component/README.md`
§ 4's "global concern"), not deciding the root JSON shape a specific
firmware target expects. That decision belongs in its own small
mapper, same as every other Remora-specific shape in this package
(`RemoraStepperHalMapper`, `RemoraDriverFirmwareMapper`).

Root shape verified against the real, working
`machine_config/example/ender3/config.txt` — `{"Board": ..., "Modules":
[...]}`, no top-level `"Thread"` frequency block.
"""

from __future__ import annotations

from typing import Any

#: `config.txt`'s `"Board"` when the MCU declares none — the real
#: reference config (`machine_config/example/ender3/config.txt`) uses
#: this exact name, and `board` is never autofilled onto the MCU
#: record itself (`.agent/component/mcu_spi_remora.md` § 1) — this
#: fallback is `config.txt`-only, not something a `hardware.json`
#: reader would ever see.
DEFAULT_FIRMWARE_BOARD = "BIGTREETECH OCTOPUS"


class RemoraFirmwareConfigMapper:
    """Builds the `{"Board", "Modules"}` root object for one MCU's `config.txt`."""

    @staticmethod
    def to_config(mcu: dict[str, Any], modules: list[dict[str, object]]) -> dict[str, Any]:
        return {
            "Board": mcu.get("board") or DEFAULT_FIRMWARE_BOARD,
            "Modules": modules,
        }


__all__ = ["DEFAULT_FIRMWARE_BOARD", "RemoraFirmwareConfigMapper"]
