from .connection import (
    HAS_HAL,
    USE_MOCK,
    Connection,
    DeviceConfigMapper,
    HalSubscriptionManager,
    connection,
    execute_gcode,
    execute_sync_cmd,
    get_machine_cmd,
    get_machine_error,
    get_machine_stat,
    hal_manager,
    is_linuxcnc_connected,
    linuxcnc,
    hal
)

__all__ = [
    "USE_MOCK",
    "HAS_HAL",
    "linuxcnc",
    "get_machine_stat",
    "get_machine_cmd",
    "get_machine_error",
    "is_linuxcnc_connected",
    "execute_sync_cmd",
    "execute_gcode",
    "Connection",
    "connection",
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




