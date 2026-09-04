from typing import Optional
from pathlib import Path
from .FileService import FileService
from . import paths

class MacroFileService(FileService):
    """Manages LinuxCNC macros (.macro) and subroutines (.ngc)."""

    default_read_only = False
    ALLOWED_EXTENSIONS = (".macro", ".ngc")

    @classmethod
    def macro_filter(cls, name: str) -> bool:
        return name.lower().endswith(cls.ALLOWED_EXTENSIONS)

    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__(root or paths.MACROS_DIR)
        self.filename_filter = self.macro_filter