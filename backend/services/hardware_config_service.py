import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class HardwareConfigService:
    def __init__(self, active_path: Optional[Path] = None):
        self.active_path = active_path

    def _resolve_active_path(self) -> Path:
        if self.active_path:
            return self.active_path
        return Path("machine_config/active/hardware.json")

    def load_payload(self) -> Dict[str, Any]:
        """Loads and parses the hardware.json file safely."""
        path = self._resolve_active_path()

        if not path.exists():
            logger.debug("HardwareConfigService: %s missing — returning {}", path)
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
        payload = self.load_payload()
        raw_tools = payload.get("tools")

        if isinstance(raw_tools, list):
            return raw_tools
        return []

    def get_axes(self) -> List[Dict[str, Any]]:
        payload = self.load_payload()
        raw_axes = payload.get("axes")

        if isinstance(raw_axes, list):
            return raw_axes
        return []