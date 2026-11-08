import logging
from typing import Iterable, Optional, List
from pathlib import Path

from core.gcode_converter import convert, needs_conversion, ngc_name

from .FileService import FileService, FileMetadata
from . import paths

logger = logging.getLogger("backend.domain_file_services.programs")

class ProgramFileService(FileService):
    """Manages G-code files in ``nc_files/``."""

    default_read_only = False
    #: ``.gcode`` / ``.gco`` / ``.g`` are converted to ``.ngc`` on upload.
    ALLOWED_EXTENSIONS = (".gcode", ".gco", ".g", ".ngc")

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

    def save_upload(self, filename: str, data: bytes, macro_names: Optional[Iterable[str]] = None) -> str:
        """Store an upload; returns the path it was stored under.

        A slicer's ``.gcode`` is converted to LinuxCNC NGC and stored as
        ``.ngc`` (``core.gcode_converter``: ``E`` -> ``A``, Marlin M-codes,
        ``start 60 200`` -> ``o<start> call [60] [200]`` for a macro in
        ``macros/``). An ``.ngc`` is stored as it is.
        """
        if not needs_conversion(filename):
            self.write_bytes(filename, data, overwrite=True)
            return filename
        names = list(macro_names) if macro_names is not None else self._macro_names()
        result = convert(data.decode("utf-8", errors="replace"), names, self._led_names())
        stored = ngc_name(filename)
        self.write_bytes(stored, result.text.encode("utf-8"), overwrite=True)
        logger.info("Converted %s -> %s (%d note(s))", filename, stored, len(result.notes))
        for note in result.notes[:50]:
            logger.info("  %s: %s", stored, note)
        return stored

    @staticmethod
    def _led_names() -> List[str]:
        """The active machine's ``[neopixel]`` names, in order (``M150`` /
        ``SET_LED`` -> ``M183``); none without a machine."""
        import json

        try:
            payload = json.loads(paths.default_machine_hardware_json().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [str(led["id"]) for led in payload.get("leds") or [] if isinstance(led, dict) and led.get("id")]

    @staticmethod
    def _macro_names() -> List[str]:
        """``macros/<name>.ngc`` — what ``start 60 200`` lines may call."""
        try:
            return sorted(p.stem for p in Path(paths.MACROS_DIR).glob("*.ngc"))
        except OSError:
            return []

    #: Loaded by "unload" (the machine backend's empty program) — never deleted.
    EMPTY_PROGRAM = "EmptyProgram.ngc"

    def delete_file(self, filename: str, recursive: bool = False) -> None:
        if self.safe_join(filename) == self.safe_join(self.EMPTY_PROGRAM):
            raise PermissionError(f"{self.EMPTY_PROGRAM} is needed to unload programs")
        self.delete(filename, recursive=recursive)

    def resolve_program_path(self, filename: str) -> Path:
        return self.safe_join(filename)

    def list_program_files(self) -> List[FileMetadata]:
        return [file for file in self.list_files() if file.path != self.EMPTY_PROGRAM]