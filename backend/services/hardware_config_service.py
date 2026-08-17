"""Shared helper for reading the active ``hardware.json``.

Centralises the path-resolution and JSON-parse logic that every
backend feature used to duplicate. The class wraps the previous
``load_active_tools`` / ``load_active_heaters`` helpers behind one
``active_path`` parameter so a test can point at a ``tmp_path``
without monkey-patching module-level globals.

Resolution order (first match wins):

1. ``active_path`` passed explicitly to ``__init__``.
2. ``repo_root`` / ``machine_config/active/hardware.json`` when the
   caller passes a repo root (typical for tests).
3. The current process's working directory
   (``machine_config/active/hardware.json``) when neither of the
   above is set — matches the historical
   ``Path("machine_config/active/hardware.json")`` fallback.

The class intentionally swallows ``OSError`` /
``json.JSONDecodeError`` so a missing / corrupt payload surfaces as
an empty dict (the dashboard's empty-state UI handles that), not a
5xx that blanks the panel.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class HardwareConfigService:
    """Read-only facade over the active ``hardware.json`` payload.

    Parameters
    ----------
    active_path:
        Direct override for the ``hardware.json`` location. Takes
        precedence over ``repo_root``.
    repo_root:
        Project root; ``hardware.json`` is read from
        ``<repo_root>/machine_config/active/hardware.json``. Useful
        for tests that want to point the loader at a temp directory
        without monkey-patching module-level globals.
    """

    def __init__(
        self,
        active_path: Optional[Path] = None,
        repo_root: Optional[Path] = None,
    ) -> None:
        self.active_path = active_path
        self.repo_root = repo_root

    def _resolve_active_path(self) -> Path:
        if self.active_path is not None:
            return Path(self.active_path)
        if self.repo_root is not None:
            return Path(self.repo_root) / "machine_config" / "active" / "hardware.json"

        # FIX: Make the fallback path absolute, resolving relative to this file!
        # .parents[0] = services/
        # .parents[1] = backend/
        # .parents[2] = LinuxCNC_UI/ (Project Root)
        project_root = Path(__file__).resolve().parents[2]
        return project_root / "machine_config" / "active" / "hardware.json"

    def load_payload(self) -> Dict[str, Any]:
        """Load and parse the active ``hardware.json`` file safely."""
        path = self._resolve_active_path()

        if not path.exists():
            logger.info("HardwareConfigService: %s missing — returning {}", path)
            return {}

        try:
            with path.open(encoding="utf-8") as fp:
                payload = json.load(fp)
            if isinstance(payload, dict):
                return payload
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "HardwareConfigService: failed to parse %s: %s — returning {}",
                path,
                exc,
            )
            return {}

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return the raw ``tools[]`` array from the active payload."""
        payload = self.load_payload()
        raw_tools = payload.get("tools")
        if isinstance(raw_tools, list):
            return raw_tools
        return []

    def get_axes(self) -> List[Dict[str, Any]]:
        """Return the raw ``axes[]`` array from the active payload."""
        payload = self.load_payload()
        raw_axes = payload.get("axes")
        if isinstance(raw_axes, list):
            return raw_axes
        return []

    def get_temperature_sensors(self) -> List[Dict[str, Any]]:
        """Return the raw ``temperature_sensors[]`` array from the active payload."""
        payload = self.load_payload()
        raw_sensors = payload.get("temperature_sensors")
        if isinstance(raw_sensors, list):
            return raw_sensors
        return []


__all__ = ["HardwareConfigService"]
