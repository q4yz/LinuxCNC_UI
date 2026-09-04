"""Service layer for the system service.

Re-exports the shared domain file services (living in the
``domain_file_services`` package inside ``backend/common/``) so the
system routers can import them from a single, clean path:

    from services import ConfigFileService, StagedFileService
    from services import get_config_service, get_staged_service

The system-owned services (machineconfig compiler pipeline, machine
templates, macro CRUD, machine lifecycle) live in their respective
modules and are imported directly from there.
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
    "domain_file_services",
    "get_active_service",
    "get_config_service",
    "get_machine_service",
    "get_mcode_service",
    "get_macro_service",
    "get_program_service",
    "get_staged_service",
    "reset_service_cache",
]
