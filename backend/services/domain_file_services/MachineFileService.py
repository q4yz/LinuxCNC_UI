from typing import Optional
from pathlib import Path
from .FileService import FileService
from .paths import MACHINES_DIR


class MachineFileService(FileService):
    """Manages ``machine_config/machines/``.

    Holds one folder per generated machine (``<machine>/configs/`` with
    the machine.ini / machine.hal / hardware.json / machine.cfg set).
    Folders are supported at any depth so operators can group machines.
    Unlike staged / active this root is **writable** — the generated
    files are templates the operator is expected to hand-edit.
    """

    default_read_only = False

    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__(root or MACHINES_DIR)
