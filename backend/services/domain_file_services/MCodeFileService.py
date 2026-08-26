import re
from typing import Optional
from pathlib import Path
from .FileService import FileService
from .paths import M_CODES_DIR

class MCodeFileService(FileService):
    """Manages LinuxCNC custom M-codes in ``machine_config/m_codes/``."""

    default_read_only = False
    MCODE_NAME = re.compile(r"^M1\d{2}$")
    KIND = "mcode"

    @classmethod
    def mcode_filter(cls, name: str) -> bool:
        return bool(cls.MCODE_NAME.match(name))

    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__(root or M_CODES_DIR)
        self.filename_filter = self.mcode_filter