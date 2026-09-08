from typing import Optional, List
from pathlib import Path
from .FileService import FileService, FileMetadata
from . import paths

class ProgramFileService(FileService):
    """Manages G-code files in ``nc_files/``."""

    default_read_only = False
    ALLOWED_EXTENSIONS = (".gcode", ".ngc")

    @classmethod
    def gcode_filter(cls, name: str) -> bool:
        return name.lower().endswith(cls.ALLOWED_EXTENSIONS)

    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__(root or paths.NC_FILES_DIR)
        self.filename_filter = self.gcode_filter

    def read_head(self, filename: str, max_bytes: int = 524_288) -> bytes:
        """Read at most ``max_bytes`` raw bytes from the file's start.

        Slicer-embedded thumbnails (the ``; thumbnail begin/end``
        base64 comment blocks Cura / PrusaSlicer / Orca write) always
        live at the top of a program file, so the thumbnail endpoint
        can avoid loading multi-megabyte programs just to render a
        list icon.
        """
        path = self.resolve_program_path(filename)
        with path.open("rb") as fp:
            return fp.read(max_bytes)

    def save_upload(self, filename: str, data: bytes) -> None:
        self.write_bytes(filename, data, overwrite=True)

    def delete_file(self, filename: str) -> None:
        self.delete(filename)

    def resolve_program_path(self, filename: str) -> Path:
        return self.safe_join(filename)

    def list_program_files(self) -> List[FileMetadata]:
        return [file for file in self.list_files() if file.name != "EmptyProgram.ngc"]