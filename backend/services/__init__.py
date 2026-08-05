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
    ProgramFileService,
    StagedFileService,
    get_active_service,
    get_config_service,
    get_program_service,
    get_staged_service,
    reset_service_cache,
)
from .macro_executor import CNCInterface, execute_macro
from .macro_parser import parse_macro, validate_macro_name
from .macro_storage import MacroFile, MacroStorage

__all__ = [
    "ActiveFileService",
    "CNCInterface",
    "ConfigFileService",
    "FileMetadata",
    "FileService",
    "MacroFile",
    "MacroStorage",
    "ProgramFileService",
    "StagedFileService",
    "execute_macro",
    "get_active_service",
    "get_config_service",
    "get_program_service",
    "get_staged_service",
    "parse_macro",
    "reset_service_cache",
    "validate_macro_name",
]
