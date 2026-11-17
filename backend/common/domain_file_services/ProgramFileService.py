import logging
import threading
import time
from typing import Any, Dict, Iterable, List, Optional
from pathlib import Path

from core.gcode_converter import convert, needs_conversion, ngc_name

from .FileService import FileService, FileMetadata
from . import paths

logger = logging.getLogger("backend.domain_file_services.programs")

#: Uploads converting in the background: the stored path -> state
#: (``started``, ``error``). Shared by every service instance (one per request).
_CONVERSIONS: Dict[str, Dict[str, Any]] = {}
_CONVERSIONS_LOCK = threading.Lock()
#: How long a failed conversion stays in the listing (s).
FAILED_SHOWN_S = 600.0


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

    def save_upload(self, filename: str, data: bytes, macro_names: Optional[Iterable[str]] = None,
                    background: bool = False) -> str:
        """Store an upload; returns the path it was (or will be) stored under.

        A slicer's ``.gcode`` is converted to LinuxCNC NGC and stored as
        ``.ngc`` (``core.gcode_converter``: ``E`` -> ``A``, Marlin M-codes,
        ``start 60 200`` -> ``o<start> call [60] [200]`` for a macro in
        ``macros/``). An ``.ngc`` is stored as it is.

        ``background``: convert on a thread and return at once — a big
        print takes a while on a small host; the listing shows the file
        as ``converting`` until it is written (atomically: LinuxCNC never
        sees half a program).
        """
        if not needs_conversion(filename):
            self.write_bytes(filename, data, overwrite=True)
            return filename
        if background:
            stored = ngc_name(filename)
            self.safe_join(stored)  # rejects a bad path now, not on the thread
            with _CONVERSIONS_LOCK:
                if (_CONVERSIONS.get(stored) or {}).get("error") is None and stored in _CONVERSIONS:
                    raise FileExistsError(f"{stored} is still being converted")
                _CONVERSIONS[stored] = {"started": time.time(), "error": None}
            threading.Thread(target=self._convert_in_background, args=(filename, data, macro_names),
                             name=f"convert {stored}", daemon=True).start()
            return stored
        return self._convert_and_store(filename, data, macro_names)

    def _convert_in_background(self, filename: str, data: bytes, macro_names: Optional[Iterable[str]]) -> None:
        stored = ngc_name(filename)
        started = time.monotonic()
        try:
            self._convert_and_store(filename, data, macro_names)
        except Exception as exc:  # noqa: BLE001 - reported in the listing
            logger.exception("Converting %s failed", filename)
            with _CONVERSIONS_LOCK:
                _CONVERSIONS[stored] = {"started": time.time(), "error": str(exc) or type(exc).__name__}
            return
        with _CONVERSIONS_LOCK:
            _CONVERSIONS.pop(stored, None)
        logger.info("Converted %s in %.1f s", filename, time.monotonic() - started)

    def _convert_and_store(self, filename: str, data: bytes, macro_names: Optional[Iterable[str]]) -> str:
        names = list(macro_names) if macro_names is not None else self._macro_names()
        payload = self._machine_payload()
        retraction = payload.get("firmware_retraction") if payload else None
        result = convert(data.decode("utf-8", errors="replace"), names, self._led_names(payload),
                         self._part_fans(payload), retraction if isinstance(retraction, dict) else None)
        stored = ngc_name(filename)
        target = self.safe_join(stored)
        if target.exists() and self._is_path_read_only(target):
            raise PermissionError(f"Refusing to overwrite read-only file: {stored}")
        # written next to it and renamed: a reader never gets half a program
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(f".{target.name}.part")
        part.write_bytes(result.text.encode("utf-8"))
        part.replace(target)
        logger.info("Converted %s -> %s (%d note(s))", filename, stored, len(result.notes))
        for note in result.notes[:50]:
            logger.info("  %s: %s", stored, note)
        return stored

    @staticmethod
    def _machine_payload() -> Optional[Dict[str, Any]]:
        """The active machine's ``hardware.json``; ``None`` without one."""
        import json

        from core.calibration_file import CalibrationFile, calibration_path, overlay_payload

        path = paths.default_machine_hardware_json()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        # the calibrated retraction (Calibration tab) for G10 / G11
        return overlay_payload(payload, CalibrationFile(calibration_path(path.parent)).values())

    @staticmethod
    def _part_fans(payload: Optional[Dict[str, Any]]) -> Optional[int]:
        """How many part fans ``M106 P<n>`` can reach — counted like
        ``machine_config/m_codes/M182`` (a heater's placeholder fan on the
        heater's own pin does not count); ``None`` without a machine."""
        if payload is None:
            return None

        def qualified(pin: object) -> str:
            text = str(pin or "").lstrip("!^~")
            return text if ":" in text else "mcu:" + text

        shared = {str(p) for p in payload.get("duplicate_pin_overrides") or []}
        return sum(1 for f in payload.get("fans") or []
                   if isinstance(f, dict) and f.get("id") and f.get("kind", "part") == "part"
                   and qualified(f.get("pin")) not in shared)

    @staticmethod
    def _led_names(payload: Optional[Dict[str, Any]]) -> List[str]:
        """The active machine's ``[neopixel]`` names, in order (``M150`` /
        ``SET_LED`` -> ``M183``); none without a machine."""
        if payload is None:
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
        files = [file for file in self.list_files() if file.path != self.EMPTY_PROGRAM]
        with _CONVERSIONS_LOCK:
            now = time.time()
            for path, state in list(_CONVERSIONS.items()):
                if state["error"] is not None and now - state["started"] > FAILED_SHOWN_S:
                    del _CONVERSIONS[path]
            pending = dict(_CONVERSIONS)
        by_path = {f.path: f for f in files}
        for path, state in pending.items():
            status, message = ("failed", state["error"]) if state["error"] is not None else ("converting", None)
            entry = by_path.get(path)
            if entry is None:  # a new file: listed while it converts
                parent = path.rsplit("/", 1)[0] if "/" in path else None
                entry = FileMetadata(name=path.rsplit("/", 1)[-1], path=path, parent=parent, kind="file")
                files.append(entry)
            entry.status, entry.message = status, message
        return files

    @staticmethod
    def conversion_state(path: str) -> Optional[Dict[str, Any]]:
        with _CONVERSIONS_LOCK:
            state = _CONVERSIONS.get(path)
            return dict(state) if state else None