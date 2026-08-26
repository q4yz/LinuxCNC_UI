from typing import Optional, List
from pathlib import Path

from .ActiveFileService import ActiveFileService
from .FileService import FileService

from .paths import STAGED_DIR

class StagedFileService(FileService):
    """Manages ``machine_config/ready_for_deploy/``."""

    default_read_only = True

    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__(root or STAGED_DIR)

    def clear_and_stage(self, compiler, source: Path) -> List[Path]:
        self.clear_directory()
        return list(compiler.compile(source, self.root))

    def mark_read_only(self) -> int:
        return 0

    def is_empty(self) -> bool:
        if not self.root.exists():
            return True
        return not any(self.root.iterdir())

    def deploy_to_active(self, active_service: ActiveFileService) -> List[str]:
        if self.is_empty():
            raise FileNotFoundError("Staging area is empty. Compile a profile before deploying.")
        active_service.clear_directory()
        return self.copy_tree(self.root, active_service.root)