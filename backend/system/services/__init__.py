"""Service layer for the system service.

Re-exports the shared domain file services (living in the
``domain_file_services`` package inside ``backend/common/``) so the
system routers can import them from a single, clean path:

    from services import ConfigFileService
    from services import get_config_service

The system-owned services (machine templates, macro CRUD, machine
lifecycle) live in their respective modules and are imported directly
from there.
"""
import domain_file_services
from domain_file_services import (
    ConfigFileService,
    FileMetadata,
    FileService,
    MCodeFileService,
    MachineFileService,
    MacroFileService,
    ProgramFileService,
    get_config_service,
    get_machine_service,
    get_mcode_service,
    get_macro_service,
    get_program_service,
    reset_service_cache,
)

__all__ = [
    "ConfigFileService",
    "FileMetadata",
    "FileService",
    "MCodeFileService",
    "MachineFileService",
    "MacroFileService",
    "ProgramFileService",
    "domain_file_services",
    "get_config_service",
    "get_machine_service",
    "get_mcode_service",
    "get_macro_service",
    "get_program_service",
    "reset_service_cache",
]
