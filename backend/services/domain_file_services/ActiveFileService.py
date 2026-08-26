from typing import Optional, List
from pathlib import Path
from .FileService import FileService, FileMetadata
from .paths import ACTIVE_DIR

class ActiveFileService(FileService):
    """Manages ``machine_config/active/``."""

    default_read_only = True

    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__(root or ACTIVE_DIR)

    def list_active_files(self) -> List[FileMetadata]:
        return [entry for entry in self.list_files() if entry.kind == "file"]

    def machine_name(self) -> Optional[str]:
        return self.parse_machine_name()