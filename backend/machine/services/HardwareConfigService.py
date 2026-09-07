"""Shared helper for reading the current machine's ``hardware.json``.

Centralises the path-resolution and JSON-parse logic that every
backend feature used to duplicate. The class wraps the previous
``load_active_tools`` / ``load_active_heaters`` helpers behind one
``active_path`` parameter so a test can point at a ``tmp_path``
without monkey-patching module-level globals.

Resolution order (first match wins):

1. ``active_path`` passed explicitly to ``__init__``.
2. ``repo_root`` / the persisted default machine's
   ``machine_config/machines/<name>/config/hardware.json`` (falling
   back to ``configs/hardware.json``) when the caller passes a repo
   root (typical for tests).
3. The real repository root's default-machine ``hardware.json`` when
   neither of the above is set.

There is no more ``machine_config/active/`` — a machine's config
lives directly under ``machine_config/machines/<name>/`` (see
``domain_file_services.paths.default_machine_hardware_json``, which
this class delegates to for the actual name+path resolution: it
reads the persisted ``machine_config/default_machine.json`` pointer,
a plain filesystem read with no cross-app import, so this stays
usable from the machine backend without depending on the system
service's process being up).

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

from domain_file_services.paths import default_machine_hardware_json  # noqa: E402 - common lives on sys.path

logger = logging.getLogger(__name__)


class HardwareConfigService:
    """Read-only facade over the default machine's ``hardware.json``.

    Parameters
    ----------
    active_path:
        Direct override for the ``hardware.json`` location. Takes
        precedence over ``repo_root``. Named ``active_path`` for
        historical reasons (predates the removal of
        ``machine_config/active/``) — it's just "use exactly this
        file," not tied to the old active-folder concept.
    repo_root:
        Project root to resolve the default machine's config
        relative to. Useful for tests that want to point the loader
        at a temp directory without monkey-patching module-level
        globals.
    """

    def __init__(self, active_path: Optional[Path] = None, repo_root: Optional[Path] = None) -> None:
        self.active_path = active_path
        self.repo_root = repo_root

    def _resolve_hardware_json_path(self) -> Path:
        if self.active_path is not None:
            return Path(self.active_path)
        return default_machine_hardware_json(self.repo_root)

    def load_payload(self) -> Dict[str, Any]:
        """Load and parse the default machine's ``hardware.json`` safely."""
        path = self._resolve_hardware_json_path()

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
        """Return the raw ``tools[]`` array from the payload."""
        payload = self.load_payload()
        raw_tools = payload.get("tools")
        if isinstance(raw_tools, list):
            return raw_tools
        return []

    def get_axes(self) -> List[Dict[str, Any]]:
        """Return the raw ``axes[]`` array from the payload."""
        payload = self.load_payload()
        raw_axes = payload.get("axes")
        if isinstance(raw_axes, list):
            return raw_axes
        return []

    def get_joints(self) -> List[Dict[str, Any]]:
        payload = self.load_payload()
        raw_axes = payload.get("joints")
        if isinstance(raw_axes, list):
            return raw_axes
        return []

    def get_temperature_sensors(self) -> List[Dict[str, Any]]:
        """Return the raw ``temperature_sensors[]`` array from the payload."""
        payload = self.load_payload()
        raw_sensors = payload.get("temperature_sensors")
        if isinstance(raw_sensors, list):
            return raw_sensors
        return []


__all__ = ["HardwareConfigService"]
