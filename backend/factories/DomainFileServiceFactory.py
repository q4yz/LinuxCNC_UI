"""Service factory helpers for domain file services."""
from pathlib import Path
from typing import Optional, Dict

from services.domain_file_services import FileService
from services.domain_file_services.ActiveFileService import ActiveFileService
from services.domain_file_services.ConfigFileService import ConfigFileService
from services.domain_file_services.MCodeFileService import MCodeFileService
from services.domain_file_services.MacroFileService import MacroFileService
from services.domain_file_services.ProgramFileService import ProgramFileService
from services.domain_file_services.StagedFileService import StagedFileService

_SERVICE_CACHE: Dict[str, FileService] = {}

def _cache_key(cls: type, root: Optional[Path]) -> str:
    return f"{cls.__name__}:{Path(root).resolve() if root else '<default>'}"

def get_config_service(root: Optional[Path] = None) -> ConfigFileService:
    key = _cache_key(ConfigFileService, root)
    if key not in _SERVICE_CACHE:
        _SERVICE_CACHE[key] = ConfigFileService(root=root)
    return _SERVICE_CACHE[key]

def get_program_service(root: Optional[Path] = None) -> ProgramFileService:
    key = _cache_key(ProgramFileService, root)
    if key not in _SERVICE_CACHE:
        _SERVICE_CACHE[key] = ProgramFileService(root=root)
    return _SERVICE_CACHE[key]

def get_staged_service(root: Optional[Path] = None) -> StagedFileService:
    key = _cache_key(StagedFileService, root)
    if key not in _SERVICE_CACHE:
        _SERVICE_CACHE[key] = StagedFileService(root=root)
    return _SERVICE_CACHE[key]

def get_active_service(root: Optional[Path] = None) -> ActiveFileService:
    key = _cache_key(ActiveFileService, root)
    if key not in _SERVICE_CACHE:
        _SERVICE_CACHE[key] = ActiveFileService(root=root)
    return _SERVICE_CACHE[key]

def get_mcode_service(root: Optional[Path] = None) -> MCodeFileService:
    key = _cache_key(MCodeFileService, root)
    if key not in _SERVICE_CACHE:
        _SERVICE_CACHE[key] = MCodeFileService(root=root)
    return _SERVICE_CACHE[key]

def get_macro_service(root: Optional[Path] = None) -> MacroFileService:
    key = _cache_key(MacroFileService, root)
    if key not in _SERVICE_CACHE:
        _SERVICE_CACHE[key] = MacroFileService(root=root)
    return _SERVICE_CACHE[key]

def reset_service_cache() -> None:
    _SERVICE_CACHE.clear()

__all__ = [
    "ActiveFileService",
    "ConfigFileService",
    "MCodeFileService",
    "MacroFileService",
    "ProgramFileService",
    "StagedFileService",
    "get_active_service",
    "get_config_service",
    "get_mcode_service",
    "get_program_service",
    "get_staged_service",
    "reset_service_cache",
    "get_macro_service",
]