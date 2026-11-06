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
[...]}`. A `"Threads"` block is added only when the MCU declares
`PRU_base_freq`: the firmware's base thread then runs at the frequency
the `loadrt remora-spi PRU_base_freq=` line tells the driver, both from
the one `[mcu]` key. Without it the firmware ran its own default
(40 kHz) whatever the driver was told, and a regenerated config dropped
a hand-added block: an STM32G0 board (Manta M8P) is too slow for 40 kHz
with five step generators, it stops answering SPI and the next
`remora-upload --sync` fails.
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
        config: dict[str, Any] = {"Board": mcu.get("board") or DEFAULT_FIRMWARE_BOARD}
        threads = RemoraFirmwareConfigMapper.threads(mcu)
        if threads:
            config["Threads"] = threads
        config["Modules"] = modules
        return config

    @staticmethod
    def threads(mcu: dict[str, Any]) -> list[dict[str, object]]:
        """The firmware `"Threads"` block: the base thread at the MCU's
        `PRU_base_freq` (the same value as the driver line), `[]` when
        none is declared (firmware and driver keep their defaults)."""
        base = mcu.get("pru_base_freq")
        if not base:
            return []
        return [{"Thread": "Base", "Frequency": int(base)}]


__all__ = ["DEFAULT_FIRMWARE_BOARD", "RemoraFirmwareConfigMapper"]
