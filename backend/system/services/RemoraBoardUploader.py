"""Manual upload of a machine's ``config_<mcu>.txt`` or ``firmware.bin``
to its Remora SPI board — the Machines explorer's "Upload to board".

Runs ``remora-upload`` (Remora-m8p ``LinuxCNC/Tools``, installed by
``scripts/install_hal_components.sh``) with the same spidev / GPIO chip
select / clock as the machine's ``loadrt remora-spi`` line
(:meth:`RemoraRouterMapper.link_args`), read from the machine's own
``hardware.json``. The tool only works while LinuxCNC does not own the
SPI link; :meth:`MachineLifecycleService.upload_to_board` holds the
lifecycle lock so a start cannot race it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from exceptions import BadRequestError, NotFoundError
from services.halcompiler.mcus.RemoraRouterMapper import RemoraRouterMapper

#: firmware.bin is ~100 kB in 44-byte frames — about a minute at 1 MHz.
UPLOAD_TIMEOUT_S = 300.0
_CONFIG_FILE = re.compile(r"^config_(?P<mcu>[A-Za-z0-9_.-]+)\.txt$")
FIRMWARE_FILE = "firmware.bin"


def is_board_file(name: str) -> bool:
    """``config_<mcu>.txt`` or ``firmware.bin`` — what the board accepts."""
    return name == FIRMWARE_FILE or bool(_CONFIG_FILE.match(name))


class RemoraBoardUploader:
    def __init__(self, tool: Optional[str] = None) -> None:
        self._tool = tool or os.environ.get("REMORA_UPLOAD_TOOL") or shutil.which("remora-upload")

    def upload(self, file: Path) -> str:
        """Upload ``file`` to its machine's board; returns the tool's output."""
        if not file.is_file():
            raise NotFoundError(f"{file.name} not found")
        if not is_board_file(file.name):
            raise BadRequestError(f"{file.name}: only config_<mcu>.txt and firmware.bin can go to a board")
        mcu = self._board(file)
        if not self._tool:
            raise BadRequestError(
                "remora-upload is not installed — run once on the machine: "
                "sudo bash scripts/install_hal_components.sh"
            )

        target = FIRMWARE_FILE if file.name == FIRMWARE_FILE else "config.txt"
        command = [self._tool, *RemoraRouterMapper.link_args(mcu), "-n", target, str(file)]
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=UPLOAD_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError) as exc:
            raise BadRequestError(f"remora-upload failed: {exc}") from exc
        output = (done.stdout + done.stderr).strip()
        if done.returncode != 0:
            raise BadRequestError(f"Upload of {file.name} failed (exit {done.returncode}):\n{output}")
        return output

    @staticmethod
    def _board(file: Path) -> dict[str, Any]:
        """The remora-spi MCU ``file`` belongs to, from ``hardware.json`` next to it."""
        try:
            hardware = json.loads((file.parent / "hardware.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BadRequestError(
                f"No readable hardware.json next to {file.name} — regenerate the machine"
            ) from exc
        boards = [
            mcu for mcu in hardware.get("mcus") or []
            if isinstance(mcu, dict) and mcu.get("connection") == "remora-spi"
        ]
        match = _CONFIG_FILE.match(file.name)
        if match:
            board = next((mcu for mcu in boards if mcu.get("id") == match.group("mcu")), None)
            if board is None:
                raise BadRequestError(f"{file.name}: no remora-spi MCU '{match.group('mcu')}' in hardware.json")
            return board
        if len(boards) != 1:
            raise BadRequestError(
                f"firmware.bin needs exactly one remora-spi board in hardware.json, found {len(boards)}"
            )
        return boards[0]


__all__ = ["FIRMWARE_FILE", "RemoraBoardUploader", "is_board_file"]
