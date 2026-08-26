"""Domain file services for the machineconfig module.

Re-exports the base :class:`FileService` plus the six domain
sub-services and the factory helpers so callers can do::

    from services.domain_file_services import (
        ConfigFileService,
        MCodeFileService,
        get_config_service,
        get_mcode_service,
    )

The factory helpers are re-exported here (rather than only from
``factories.DomainFileServiceFactory``) so package-level imports
like ``from services.domain_file_services import get_program_service``
work without falling back to Python's implicit submodule import,
which would bind the submodule object to the name instead of the
factory function.
"""
from .FileService import FileMetadata, FileService
from .ActiveFileService import ActiveFileService
from .ConfigFileService import ConfigFileService
from .MCodeFileService import MCodeFileService
from .MacroFileService import MacroFileService
from .ProgramFileService import ProgramFileService
from .StagedFileService import StagedFileService

from factories.DomainFileServiceFactory import (
    get_active_service,
    get_config_service,
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
    "MacroFileService",
    "ProgramFileService",
    "StagedFileService",
    "get_active_service",
    "get_config_service",
    "get_mcode_service",
    "get_macro_service",
    "get_program_service",
    "get_staged_service",
    "reset_service_cache",
]