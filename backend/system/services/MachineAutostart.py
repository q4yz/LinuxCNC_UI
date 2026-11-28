"""Start LinuxCNC when the system service starts (the device boots).

LinuxCNC always comes up in E-stop: nothing moves or heats until the
operator (or a slicer job with *Power on for the job*) releases it.

Settings -> Machine -> *Start LinuxCNC with the device*
(``machine.autostart``, admin only, on unless switched off). Nothing
happens when no default machine is selected yet, or LinuxCNC already
runs (the service restarted, e.g. after an update).
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger("backend.system.autostart")

AUTOSTART_KEY = "machine.autostart"


def autostart_enabled() -> bool:
    from services.UiSettingsService import get_ui_settings_service

    try:
        return get_ui_settings_service().read(AUTOSTART_KEY) is not False
    except Exception:  # noqa: BLE001 - unset (404): on by default
        return True


def autostart_once() -> str:
    """Start the default machine when allowed; what happened (for the log and tests)."""
    from services.MachineLifecycleService import get_machine_lifecycle_service

    if not autostart_enabled():
        return "off"
    lifecycle = get_machine_lifecycle_service()
    machine = lifecycle.default_machine()
    if not machine:
        return "no default machine"
    if lifecycle.is_running():
        return "already running"
    try:
        lifecycle.start()
    except Exception as exc:  # noqa: BLE001 - the UI still comes up; the log says why
        logger.warning("Autostart of LinuxCNC (%s) failed: %s", machine, exc)
        return f"failed: {exc}"
    logger.info("LinuxCNC started at boot with %s (in E-stop).", machine)
    return "started"


def start_in_background() -> threading.Thread:
    thread = threading.Thread(target=autostart_once, name="linuxcnc-autostart", daemon=True)
    thread.start()
    return thread
