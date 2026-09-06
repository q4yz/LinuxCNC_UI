"""Domain file services — shared between both backend services.

Re-exports the base :class:`FileService` plus the domain
sub-services and the factory helpers so callers can do::

    from domain_file_services import (
        ConfigFileService,
        MCodeFileService,
        get_config_service,
        get_mcode_service,
    )

Both apps (machine backend and system service) keep ``backend/common/``
on ``sys.path``, so this package is always importable by its bare
name.
"""
from .FileService import FileMetadata, FileService
from .ConfigFileService import ConfigFileService
from .MachineFileService import MachineFileService
from .MCodeFileService import MCodeFileService
from .MacroFileService import MacroFileService
from .ProgramFileService import ProgramFileService

from .service_factory import (
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
    "get_config_service",
    "get_machine_service",
    "get_mcode_service",
    "get_macro_service",
    "get_program_service",
    "reset_service_cache",
]
