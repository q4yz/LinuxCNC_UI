# ---------------------------------------------------------------------------
# LAYER 1: Device Configuration Mapper (.cfg file adapter)
# ---------------------------------------------------------------------------
import configparser
import os
from typing import Optional, List


class DeviceConfigMapper:
    """Parses ``.cfg`` configuration files to extract HAL pins.

    Two naming conventions are accepted because LinuxCNC
    installations differ in how they declare endstops:

    * A dedicated ``[ENDSTOPS]`` section (some operator configs).
    * The standard LinuxCNC INI structure with ``[JOINT_<n>]`` /
      ``[AXIS_<n>]`` sections and a ``HOME_SWITCH_PIN`` option.

    When neither pattern matches (or no ``.cfg`` was loaded) the
    mapper falls back to the canonical three-axis default
    ``joint.<n>.home-sw-in`` pins so a freshly-deployed machine
    without an endstop section still yields a usable pin list.

    Callers should treat the returned list as "candidate pins" —
    the actual machine may have a non-standard configuration.
    """

    def __init__(self, cfg_file_path: Optional[str] = None) -> None:
        self._config = configparser.ConfigParser()
        if cfg_file_path and os.path.exists(cfg_file_path):
            self.load_file(cfg_file_path)

    def load_file(self, file_path: str) -> None:
        """Load or reload a ``.cfg`` file."""
        self._config.read(file_path)

    def get_endstop_hal_pin_list(self) -> List[str]:
        """Extract every configured endstop HAL pin from the ``.cfg``.

        Priority:

        1. Explicit ``[ENDSTOPS]`` section — every option value is
           treated as a HAL pin name.
        2. Per-joint / per-axis ``HOME_SWITCH_PIN`` option in the
           ``[JOINT_<n>]`` / ``[AXIS_<n>]`` sections.
        3. Canonical three-axis fallback
           (``joint.0.home-sw-in``, ``joint.1.home-sw-in``,
           ``joint.2.home-sw-in``) when nothing matches.

        Empty list is impossible — the fallback guarantees the
        caller always has pins to iterate over, even before
        ``.cfg`` has been populated.
        """
        pins = []
        # Option A: Explicit [ENDSTOPS] section in .cfg file
        if self._config.has_section("ENDSTOPS"):
            for _, pin in self._config.items("ENDSTOPS"):
                pins.append(pin)
            return pins

        # Option B: Standard LinuxCNC INI structure parsing
        # (e.g. [JOINT_0] HOME_SEQUENCE).
        for section in self._config.sections():
            if section.startswith("JOINT_") or section.startswith("AXIS_"):
                if self._config.has_option(section, "HOME_SWITCH_PIN"):
                    pins.append(self._config.get(section, "HOME_SWITCH_PIN"))

        # Fallback defaults if no .cfg is loaded
        return pins or [
            "joint.0.home-sw-in",
            "joint.1.home-sw-in",
            "joint.2.home-sw-in",
        ]