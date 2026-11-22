"""Print tuning while a print runs: the live Z offset (babystepping), the
flow (M221), excluding objects, and the slicer's progress / time left.

* **Live Z offset** — ``webgui.z-offset`` (mm), added to Z's external
  offset in HAL (with the bed mesh and the Pause & Inspect lift).
  ``SET_GCODE_OFFSET Z=<mm>`` / ``Z_ADJUST=<mm>`` (console, macros;
  ``M185`` in converted files), the Job card's buttons.
* **Flow** — ``webgui.flow`` (%), the Remora ``extruder`` component's
  flow stage scales the extruder's moves. ``M221 S<%>`` (``M184``).
* **Exclude object** — ``webgui.exclude-object-<n>``: a converted file
  wraps each object's moves in ``o<…> if [#<_hal[webgui.exclude-object-n]>
  GT 0]`` (``core.gcode_converter``), its header lists the objects. Takes
  effect for the moves the interpreter has not read ahead yet.
* **Pressure advance** — ``webgui.pressure-advance`` (mm per mm/s) into
  the ``extruder`` component; starts at the profile's ``[extruder]
  pressure_advance``. ``SET_PRESSURE_ADVANCE ADVANCE=<k>`` (console),
  ``M900 K<k>`` / ``M186`` in files.
* **Progress** — the slicer's ``M73 P<%> R<min>`` lines (kept as
  comments by the converter) at or before the line that runs now.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from core.gcode_converter import MAX_OBJECTS, read_objects
from dtos.pins.HalPin import HalDataType
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from exceptions import BadRequestError
from services.HalPinService import HalPinService

logger = logging.getLogger("backend.services.print_tuning")

Z_OFFSET_LIMIT_MM = 2.0
FLOW_MIN, FLOW_MAX = 10.0, 500.0
PRESSURE_ADVANCE_MAX = 2.0
_M73 = re.compile(r"^\s*;?\s*M0*73\b([^;]*)", re.IGNORECASE)
_PARAM = re.compile(r"([A-Za-z_]+)\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+))")


@dataclass(frozen=True)
class Progress:
    percent: Optional[float]
    remaining_min: Optional[float]


def m73_index(lines: List[str]) -> List[Tuple[int, Optional[float], Optional[float]]]:
    """``(line number from 1, percent, minutes left)`` of every ``M73`` with
    a ``P`` or ``R`` (also the converter's ``; M73 …`` comments)."""
    index = []
    for number, line in enumerate(lines, start=1):
        match = _M73.match(line)
        if not match:
            continue
        words = dict(re.findall(r"([PR])\s*([-+]?(?:\d+\.?\d*|\.\d+))", match.group(1).upper()))
        if words:
            percent = float(words["P"]) if "P" in words else None
            remaining = float(words["R"]) if "R" in words else None
            index.append((number, percent, remaining))
    return index


def progress_at(index: List[Tuple[int, Optional[float], Optional[float]]], line: int) -> Optional[Progress]:
    """The last ``M73`` at or before ``line``; ``None`` before the first."""
    percent = remaining = None
    found = False
    for number, p, r in index:
        if number > line:
            break
        found = True
        percent = p if p is not None else percent
        remaining = r if r is not None else remaining
    return Progress(percent, remaining) if found else None


class PrintTuningService(HalPinService):
    def __init__(self) -> None:
        self._z_offset = 0.0
        self._flow = 100.0
        self._pressure_advance = 0.0
        self._excluded: set[int] = set()
        self._pins: dict[str, ReadWriteDynamicHalPin[Any]] = {}
        self._lock = threading.Lock()
        self._file_cache: Tuple[str, float, List[str], List[Tuple[int, Optional[float], Optional[float]]]] | None = None

    # -- HAL --------------------------------------------------------------- #

    def preload_hal_pins(self) -> None:
        self._pins["z-offset"] = ReadWriteDynamicHalPin(
            "z-offset", HalDataType.FLOAT, "Live Z offset (mm), added to Z's external offset")
        self._pins["flow"] = ReadWriteDynamicHalPin(
            "flow", HalDataType.FLOAT, "Flow (%): the extruder component scales the extruder's moves")
        for k in range(MAX_OBJECTS):
            self._pins[f"exclude-object-{k}"] = ReadWriteDynamicHalPin(
                f"exclude-object-{k}", HalDataType.BIT, f"Exclude object {k} of the loaded print")
        self._pins["pressure-advance"] = ReadWriteDynamicHalPin(
            "pressure-advance", HalDataType.FLOAT, "Pressure advance (mm per mm/s) for the extruder component")
        self._pressure_advance = self._configured_pressure_advance()
        self._flow = self._configured_flow()

    def apply_initial(self) -> None:
        """Write the start values (after ``HalPin.initialize_component``)."""
        self._write("flow", self._flow)
        self._write("z-offset", self._z_offset)
        self._write("pressure-advance", self._pressure_advance)

    @staticmethod
    def _configured_pressure_advance() -> float:
        """The profile's ``[extruder] pressure_advance`` (0 without one)."""
        from services.machine.HardwareConfigService import HardwareConfigService

        for tool in HardwareConfigService().load_payload().get("tools") or []:
            if isinstance(tool, dict) and tool.get("type") == "extruder":
                return float(tool.get("pressure_advance") or 0.0)
        return 0.0

    @staticmethod
    def _configured_flow() -> float:
        """The calibrated flow (Calibration tab, calibration.ini), else 100 %."""
        from services.machine.HardwareConfigService import HardwareConfigService

        for tool in HardwareConfigService().load_payload().get("tools") or []:
            if isinstance(tool, dict) and tool.get("type") == "extruder" and tool.get("flow"):
                return float(tool["flow"])
        return 100.0

    def _write(self, pin: str, value: Any) -> None:
        handle = self._pins.get(pin)
        if handle is not None:
            handle.set_value(value)

    # -- Z offset / flow ---------------------------------------------------- #

    @property
    def z_offset(self) -> float:
        return self._z_offset

    @property
    def flow(self) -> float:
        return self._flow

    def set_z_offset(self, value: float) -> float:
        if abs(value) > Z_OFFSET_LIMIT_MM:
            raise BadRequestError(f"Z offset {value:g} mm is beyond ±{Z_OFFSET_LIMIT_MM:g} mm.")
        self._z_offset = round(float(value), 4)
        self._write("z-offset", self._z_offset)
        logger.info("Live Z offset: %+.3f mm", self._z_offset)
        return self._z_offset

    def adjust_z_offset(self, delta: float) -> float:
        return self.set_z_offset(self._z_offset + float(delta))

    def set_flow(self, percent: float) -> float:
        if not FLOW_MIN <= percent <= FLOW_MAX:
            raise BadRequestError(f"Flow {percent:g} % is outside {FLOW_MIN:g} … {FLOW_MAX:g} %.")
        self._flow = round(float(percent), 2)
        self._write("flow", self._flow)
        logger.info("Flow: %.1f %%", self._flow)
        return self._flow

    @property
    def pressure_advance(self) -> float:
        return self._pressure_advance

    def set_pressure_advance(self, value: float) -> float:
        if not 0.0 <= value <= PRESSURE_ADVANCE_MAX:
            raise BadRequestError(f"Pressure advance {value:g} is outside 0 … {PRESSURE_ADVANCE_MAX:g}.")
        self._pressure_advance = round(float(value), 4)
        self._write("pressure-advance", self._pressure_advance)
        logger.info("Pressure advance: %.4f", self._pressure_advance)
        return self._pressure_advance

    def run_command(self, line: str) -> bool:
        """``SET_GCODE_OFFSET Z=<mm>`` / ``Z_ADJUST=<mm>`` and
        ``SET_PRESSURE_ADVANCE ADVANCE=<k>`` typed in the console: ``True``
        when it was one."""
        text = line.split(";", 1)[0].strip()
        upper = text.upper()
        if upper.startswith("SET_PRESSURE_ADVANCE"):
            params = {k.upper(): float(v) for k, v in _PARAM.findall(text)}
            if "ADVANCE" not in params:
                raise BadRequestError("SET_PRESSURE_ADVANCE: ADVANCE=<k>.")
            self.set_pressure_advance(params["ADVANCE"])
            from services.machine.ConsoleLogger import LogLevel, get_console_logger

            get_console_logger().log_event(f"Pressure advance: {self._pressure_advance:.4f}", level=LogLevel.INFO,
                                           source="CMD")
            return True
        if not upper.startswith("SET_GCODE_OFFSET"):
            return False
        params = {k.upper(): float(v) for k, v in _PARAM.findall(text)}
        if "Z_ADJUST" in params:
            self.adjust_z_offset(params["Z_ADJUST"])
        elif "Z" in params:
            self.set_z_offset(params["Z"])
        else:
            raise BadRequestError("SET_GCODE_OFFSET: Z=<mm> or Z_ADJUST=<mm>.")
        from services.machine.ConsoleLogger import LogLevel, get_console_logger

        get_console_logger().log_event(f"Live Z offset: {self._z_offset:+.3f} mm", level=LogLevel.INFO, source="CMD")
        return True

    # -- the loaded file: objects and progress ------------------------------ #

    def _file(self, path: str) -> Tuple[List[str], List[Tuple[int, Optional[float], Optional[float]]]]:
        """The loaded file's objects and M73 index, cached by path + mtime."""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return [], []
        with self._lock:
            cache = self._file_cache
            if cache is not None and cache[0] == path and cache[1] == mtime:
                return cache[2], cache[3]
            try:
                with open(path, encoding="utf-8", errors="ignore") as fp:
                    lines = fp.read().splitlines()
            except OSError:
                return [], []
            objects = read_objects("\n".join(lines[:5]))
            index = m73_index(lines)
            if cache is None or cache[0] != path:
                self._reset_objects_locked()
            self._file_cache = (path, mtime, objects, index)
            return objects, index

    def set_excluded(self, index: int, excluded: bool, path: str) -> None:
        objects, _ = self._file(path)
        if not 0 <= index < len(objects):
            raise BadRequestError(f"The loaded program has no object {index}.")
        with self._lock:
            (self._excluded.add if excluded else self._excluded.discard)(index)
        self._write(f"exclude-object-{index}", bool(excluded))
        logger.info("Object %d (%s) %s", index, objects[index], "excluded" if excluded else "included again")

    def reset_objects(self) -> None:
        """A new program: every object prints."""
        with self._lock:
            self._reset_objects_locked()

    def _reset_objects_locked(self) -> None:
        for k in list(self._excluded):
            self._write(f"exclude-object-{k}", False)
        self._excluded.clear()

    def state(self, path: str, line: int) -> dict[str, Any]:
        objects, index = self._file(path) if path else ([], [])
        progress = progress_at(index, line) if index else None
        return {
            "z_offset": self._z_offset,
            "flow": self._flow,
            "pressure_advance": self._pressure_advance,
            "objects": [{"index": k, "name": name, "excluded": k in self._excluded} for k, name in enumerate(objects)],
            "progress": None if progress is None else {"percent": progress.percent,
                                                       "remaining_min": progress.remaining_min},
        }


_SERVICE: Optional[PrintTuningService] = None


def get_print_tuning_service() -> PrintTuningService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = PrintTuningService()
    return _SERVICE


__all__ = ["PrintTuningService", "Progress", "get_print_tuning_service", "m73_index", "progress_at"]
