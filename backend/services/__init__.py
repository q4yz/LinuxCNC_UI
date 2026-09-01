"""Service layer for the LinuxCNC UI backend.

Re-exports the :class:`FileService` base, the domain sub-services,
and the factory helpers so the rest of the codebase can import them
from a single, clean path:

    from services import ConfigFileService, StagedFileService
    from services import get_config_service, get_staged_service

The routers (``backend/routers/`` and the
``backend/modules/machineconfig/router.py`` module router) are
the only consumers — they stay thin HTTP wrappers and delegate
the actual filesystem work to one of the services.

The per-module service classes (``StateService``, ``AxisService``,
``ProgramService``, ``ToolsService``, ``TemperatureService``) live
in their respective modules (``modules/<name>/tool_service.py``) and
must be imported directly from there — they are intentionally not
re-exported from this package surface.
"""
from .domain_file_services import (
    ActiveFileService,
    ConfigFileService,
    FileMetadata,
    FileService,
    MCodeFileService,
    MachineFileService,
    MacroFileService,
    ProgramFileService,
    StagedFileService,
    get_active_service,
    get_config_service,
    get_machine_service,
    get_mcode_service,
    get_macro_service,
    get_program_service,
    get_staged_service,
    reset_service_cache,
)

from .remora_signal_map import (
    get_pv_index,
    get_sp_index,
    invalidate_cache as reset_remora_signal_map_cache,
)
from .line_count_cache import (
    count_lines,
    lookup as lookup_line_count,
    register as register_line_count,
    unregister_all as clear_line_count_cache,
)

__all__ = [
    "ActiveFileService",
    "ConfigFileService",
    "FileMetadata",
    "FileService",
    "MCodeFileService",
    "MachineFileService",
    "MacroFileService",
    "ProgramFileService",
    "StagedFileService",
    "clear_line_count_cache",
    "count_lines",
    "get_active_service",
    "get_config_service",
    "get_machine_service",
    "get_mcode_service",
    "get_macro_service",
    "get_pv_index",
    "get_program_service",
    "get_sp_index",
    "get_staged_service",
    "lookup_line_count",
    "register_line_count",
    "reset_remora_signal_map_cache",
    "reset_service_cache",
]

