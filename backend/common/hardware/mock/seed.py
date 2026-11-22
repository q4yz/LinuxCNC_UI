"""Shape the mock after a machine's ``hardware.json``.

Called by the machine backend at start (mock mode) and by tests.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from hardware.mock.LinuxCNCMock import mock_system

logger = logging.getLogger(__name__)


def reseed_from_hardware_json(path: Optional[Path] = None) -> None:
    """Register the machine described by ``path`` with the mock.

    * ``None``: the default machine, as the services read it
      (``HardwareConfigService``: calibration applied, demo heaters on
      a machine without any).
    * a directory: its ``hardware.json``.
    * a file: that file.

    A missing file is logged, not raised, so a fresh checkout still starts.
    """
    if path is None:
        from services.machine.HardwareConfigService import HardwareConfigService

        mock_system.register_hardware(HardwareConfigService().load_payload())
        return
    if path.is_dir():
        path = path / "hardware.json"
    try:
        reseed_mock_from_json(path)
    except FileNotFoundError as e:
        logger.warning(str(e))


def reseed_mock_from_json(json_path: Path) -> None:
    """Register the machine of one ``hardware.json`` file."""
    if not json_path.exists():
        raise FileNotFoundError(f"Cannot reseed mock, file missing: {json_path}")
    with open(json_path, "r", encoding="utf-8") as f:
        mock_system.register_hardware(json.load(f))


__all__ = ["reseed_from_hardware_json", "reseed_mock_from_json"]
