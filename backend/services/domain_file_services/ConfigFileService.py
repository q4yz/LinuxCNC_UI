from typing import Optional
from pathlib import Path
from .FileService import FileService
from .paths import PROFILES_DIR

class ConfigFileService(FileService):
    """Manages ``machine_config/profiles/``."""

    default_read_only = False

    @staticmethod
    def cfg_filter(name: str) -> bool:
        return name.lower().endswith(".cfg")

    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__(root or PROFILES_DIR)