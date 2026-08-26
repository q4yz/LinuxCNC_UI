from .Connection import (
    HAS_HAL,
    USE_MOCK,
    DeviceConfigMapper,
    HalSubscriptionManager,
    execute_gcode,
    execute_sync_cmd,
    get_stat_channel,
    get_cmd_channel,
    get_error_channel,
    hal_manager,
    is_linuxcnc_connected,
    linuxcnc,
    hal
)

__all__ = [
    "USE_MOCK",
    "HAS_HAL",
    "linuxcnc",
    "get_stat_channel",
    "get_cmd_channel",
    "get_error_channel",
    "is_linuxcnc_connected",
    "execute_sync_cmd",
    "execute_gcode",

    "DeviceConfigMapper",
    "HalSubscriptionManager",
    "hal_manager",
    "hal",
    "linuxcnc"
    # Note: ``MachineService`` / ``machine_service`` / ``default_mapper``
    # were removed from the ``hardware`` re-export surface to break
    # the circular import between ``backend.services.machine_service`` and
    # ``hardware.connection``. They live in
    # :mod:`backend.services.machine_service` — import from there.
]




