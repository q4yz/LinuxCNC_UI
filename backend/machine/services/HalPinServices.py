"""Every service that owns ``webgui.*`` HAL pins, in startup order.

One list, so a new service cannot be forgotten at startup (the pins it
never queued would simply not exist); ``tests/test_hal_pin_setup.py``
checks that every :class:`~services.HalPinService.HalPinService` is here.
"""
from __future__ import annotations

from typing import List

from services.HalPinService import HalPinService


def hal_pin_services() -> List[HalPinService]:
    from services.motion.AxisService import get_axis_service
    from services.motion.BedMeshService import get_bed_mesh_service
    from services.io.FansService import get_fans_service
    from services.io.IoService import get_io_service
    from services.io.LedService import get_led_service
    from services.machine.McuService import get_mcu_service
    from services.calibration.PidCalibrateService import get_pid_calibrate_service
    from services.program.PrintTuningService import get_print_tuning_service
    from services.program.ProgramService import get_program_lifecycle_service
    from services.calibration.ResonanceService import get_resonance_service
    from services.calibration.ShaperService import get_shaper_service
    from services.machine.StateService import get_state_service
    from services.temperature.TemperatureService import get_temperature_service
    from services.tools.ToolsService import get_tools_service
    from services.motion.ZTiltService import get_z_tilt_service
    from services.filament.AceService import get_ace_service

    return [
        get_tools_service(),
        get_temperature_service(),
        get_state_service(),
        get_fans_service(),
        get_mcu_service(),
        get_program_lifecycle_service(),
        get_axis_service(),
        get_bed_mesh_service(),
        get_io_service(),
        get_z_tilt_service(),
        get_led_service(),
        get_print_tuning_service(),
        get_shaper_service(),
        get_pid_calibrate_service(),
        get_resonance_service(),
        get_ace_service(),
    ]


__all__ = ["hal_pin_services"]
