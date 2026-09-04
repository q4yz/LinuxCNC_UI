"""Service layer for the machine backend.

Re-exports the shared domain file services (now living in the
``domain_file_services`` package inside ``backend/common/``) plus the
machine-side helpers so the rest of the codebase can import them from
a single, clean path:

    from services import ProgramFileService
    from services import get_program_service, reset_service_cache

The per-module services (``StateService``, ``AxisService``,
``ProgramService``, ``ToolsService``, ``TemperatureService``, …) live
in their respective modules and are imported directly from there.
"""
import domain_file_services
from domain_file_services import (
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
    "domain_file_services",
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
