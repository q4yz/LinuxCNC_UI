from typing import Optional, List
from pathlib import Path
from .FileService import FileService, FileMetadata
from .paths import NC_FILES_DIR

class ProgramFileService(FileService):
    """Manages G-code files in ``nc_files/``."""

    default_read_only = False
    ALLOWED_EXTENSIONS = (".gcode", ".ngc")

    @classmethod
    def gcode_filter(cls, name: str) -> bool:
        return name.lower().endswith(cls.ALLOWED_EXTENSIONS)

    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__(root or NC_FILES_DIR)
        self.filename_filter = self.gcode_filter

    def save_upload(self, filename: str, data: bytes) -> None:
        self.write_bytes(filename, data, overwrite=True)

    def delete_file(self, filename: str) -> None:
        self.delete(filename)

    def resolve_program_path(self, filename: str) -> Path:
        return self.safe_join(filename)

    def list_program_files(self) -> List[FileMetadata]:
        return [file for file in self.list_files() if file.name != "EmptyProgram.ngc"]