"""Service layer for the LinuxCNC UI backend.

Re-exports the :class:`FileService` base and the four domain
sub-services so the rest of the codebase can import them from a
single, clean path:

    from services import ConfigFileService, StagedFileService

The routers (``backend/routers/`` and the
``backend/modules/machineconfig/router.py`` module router) are
the only consumers — they stay thin HTTP wrappers and delegate
the actual filesystem work to one of the four services.
"""

from .file_service import FileMetadata, FileService
from .domain_file_services import (
    ActiveFileService,
    ConfigFileService,
    MCodeFileService,
    ProgramFileService,
    StagedFileService,
    get_active_service,
    get_config_service,
    get_mcode_service,
    get_program_service,
    get_staged_service,
    reset_service_cache,
)
from .remora_signal_map import (
    get_pv_index,
    get_sp_index,
    invalidate_cache as reset_remora_signal_map_cache,
)

__all__ = [
    "ActiveFileService",
    "ConfigFileService",
    "FileMetadata",
    "FileService",
    "MCodeFileService",
    "ProgramFileService",
    "StagedFileService",
    "get_active_service",
    "get_config_service",
    "get_mcode_service",
    "get_pv_index",
    "get_program_service",
    "get_sp_index",
    "get_staged_service",
    "reset_remora_signal_map_cache",
    "reset_service_cache",
] 
