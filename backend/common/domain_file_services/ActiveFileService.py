from typing import Optional, List
from pathlib import Path
from .FileService import FileService, FileMetadata
from . import paths

class ActiveFileService(FileService):
    """Manages ``machine_config/active/``."""

    default_read_only = True

    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__(root or paths.ACTIVE_DIR)

    def list_active_files(self) -> List[FileMetadata]:
        return [entry for entry in self.list_files() if entry.kind == "file"]

    def machine_name(self) -> Optional[str]:
        return self.parse_machine_name()

    def deploy_from(self, source: Path) -> List[str]:
        """Replace ``active/`` wholesale with the contents of ``source``.

        ``source`` is typically a generated machine's
        ``machines/<name>/configs/`` directory (see
        :mod:`services.machinetemplates`). The previous active
        payload is cleared first — deploy is always a full swap, not
        a merge, so a stale file from an older machine never lingers.
        """
        self.clear_directory()
        return self.copy_tree(source, self.root)