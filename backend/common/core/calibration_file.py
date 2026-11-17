"""``calibration.ini`` — the machine's calibration results, next to its
``hardware.json`` / ``machine.ini`` (``machines/<name>/config/``).

Generate never touches it; the results override the profile:

* **INI sections** (``[HEATER_EXTRUDER] PID_KP`` …, ``[INPUT_SHAPER]
  TYPE_X``): merged into ``machine.ini`` when the system backend starts
  LinuxCNC (:func:`merge_ini`, the result ``machine.calibrated.ini``).
  LinuxCNC takes the *first* value of a key, so reading a second file
  after ``machine.ini`` could not override anything.
* ``[CALIBRATION]``: values the machine backend lays over
  ``hardware.json`` (:func:`overlay_payload`) — the probe's Z offset,
  pressure advance, the shaper frequencies, the skew factor. A new probe
  Z offset also moves Z's home when Z homes on the probe
  (:func:`merge_ini`).
* ``[CALIBRATION_STATE]``: per calibration ``<id>.last`` (ISO time),
  ``<id>.result`` (text), ``<id>.remind`` (ISO date, once).

LinuxCNC never sees the two ``CALIBRATION`` sections.
"""
from __future__ import annotations

import configparser
import copy
import io
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

FILE_NAME = "calibration.ini"
CALIBRATED_INI_NAME = "machine.calibrated.ini"
VALUES = "CALIBRATION"
STATE = "CALIBRATION_STATE"
_HEADER = (
    "# Calibration results (LinuxCNC_UI, Calibration tab). They override the profile /\n"
    "# machine.ini at every machine start. Delete a line (or Clear on the card) to go back to the\n"
    "# profile's value. [CALIBRATION] / [CALIBRATION_STATE] are for the UI only.\n\n"
)
_LOCK = threading.Lock()

#: ``[CALIBRATION]`` keys.
PROBE_Z_OFFSET = "PROBE_Z_OFFSET"
PRESSURE_ADVANCE = "PRESSURE_ADVANCE"
SHAPER_FREQ = "SHAPER_FREQ_{axis}"      # X / Y
SHAPER_TYPE = "SHAPER_TYPE_{axis}"      # zv, mzv, zvd, ei
SKEW_XY = "SKEW_XY"
FLOW = "FLOW"                           # % — the print tuning's flow at start
#: ``[INPUT_SHAPER]`` of machine.ini: ``TYPE_X`` / ``TYPE_Y`` (jointshape codes).
INPUT_SHAPER_SECTION = "INPUT_SHAPER"


def calibration_path(config_dir: Path) -> Path:
    return Path(config_dir) / FILE_NAME


def _parser() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    return parser


class CalibrationFile:
    """Read / write one ``calibration.ini`` (thread-safe, written whole)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> Dict[str, Dict[str, str]]:
        parser = _parser()
        try:
            parser.read_string(self.path.read_text(encoding="utf-8"))
        except (OSError, configparser.Error):
            return {}
        return {section: dict(parser.items(section)) for section in parser.sections()}

    def _save(self, data: Mapping[str, Mapping[str, str]]) -> None:
        parser = _parser()
        for section, values in data.items():
            if values:
                parser[section] = dict(values)
        buffer = io.StringIO()
        parser.write(buffer)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".ini.tmp")
        tmp.write_text(_HEADER + buffer.getvalue(), encoding="utf-8")
        tmp.replace(self.path)

    def update(self, values: Mapping[str, Mapping[str, Optional[Any]]]) -> None:
        """Set ``{section: {key: value}}``; ``None`` removes a key."""
        with _LOCK:
            data = self.load()
            for section, keys in values.items():
                target = data.setdefault(section, {})
                for key, value in keys.items():
                    if value is None:
                        target.pop(key, None)
                    else:
                        target[key] = _text(value)
            self._save(data)

    # -- [CALIBRATION] ------------------------------------------------------ #

    def values(self) -> Dict[str, str]:
        return self.load().get(VALUES, {})

    def number(self, key: str) -> Optional[float]:
        raw = self.values().get(key)
        try:
            return float(raw) if raw is not None else None
        except ValueError:
            return None

    # -- [CALIBRATION_STATE] ------------------------------------------------ #

    def state(self, calibration_id: str) -> Dict[str, str]:
        prefix = f"{calibration_id}."
        return {k[len(prefix):]: v for k, v in self.load().get(STATE, {}).items() if k.startswith(prefix)}

    def set_state(self, calibration_id: str, **fields: Optional[Any]) -> None:
        self.update({STATE: {f"{calibration_id}.{k}": v for k, v in fields.items()}})


def _text(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value).replace("\n", " ")


# --------------------------------------------------------------------------- #
# machine.ini + calibration.ini -> machine.calibrated.ini (system backend)      #
# --------------------------------------------------------------------------- #

_SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_KEY = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=")


def ini_overrides(calibration: Mapping[str, Mapping[str, str]], payload: Mapping[str, Any],
                  machine_ini: str) -> Dict[str, Dict[str, str]]:
    """The INI keys ``calibration.ini`` sets: its INI sections, and Z's
    ``HOME_OFFSET`` / ``HOME`` moved by a new probe Z offset when Z homes
    on the probe (``probe:z_virtual_endstop``: the switch is the probe)."""
    out: Dict[str, Dict[str, str]] = {
        section: dict(keys) for section, keys in calibration.items() if not section.startswith(VALUES)
    }
    raw = (calibration.get(VALUES) or {}).get(PROBE_Z_OFFSET)
    probe = payload.get("probe") if isinstance(payload.get("probe"), dict) else None
    if raw is None or probe is None or not isinstance(payload.get("z_virtual_endstop"), dict):
        return out
    try:
        delta = float(raw) - float(probe.get("z_offset") or 0.0)
    except ValueError:
        return out
    existing = _ini_values(machine_ini)
    for axis in payload.get("axes") or []:
        if str(axis.get("id", "")).lower() != "z":
            continue
        for number in axis.get("joint_numbers") or []:
            section = f"JOINT_{int(number)}"
            for key in ("HOME_OFFSET", "HOME"):
                base = existing.get(section, {}).get(key)
                if base is not None and key not in out.get(section, {}):
                    try:
                        out.setdefault(section, {})[key] = f"{float(base) + delta:.6g}"
                    except ValueError:
                        pass
    return out


def _ini_values(text: str) -> Dict[str, Dict[str, str]]:
    """First value of every key per section (LinuxCNC's reading)."""
    values: Dict[str, Dict[str, str]] = {}
    section = None
    for line in text.splitlines():
        if (m := _SECTION.match(line)):
            section = m.group(1).strip()
            values.setdefault(section, {})
        elif section is not None and (k := _KEY.match(line)) and not line.lstrip().startswith(("#", ";")):
            values[section].setdefault(k.group(1), line.split("=", 1)[1].strip())
    return values


def merge_ini(machine_ini: str, overrides: Mapping[str, Mapping[str, str]]) -> str:
    """``machine_ini`` with ``overrides`` applied line by line: a key's
    first line in its section gets the new value (later duplicates such as
    ``HALFILE`` stay as they are), a missing key goes after the section's
    last line, a missing section at the end. Everything else is untouched."""
    lines = machine_ini.splitlines()
    pending = {section: dict(keys) for section, keys in overrides.items() if keys}
    out: List[str] = []
    section: Optional[str] = None

    def flush(current: Optional[str]) -> None:
        keys = pending.pop(current, None) if current is not None else None
        if keys:
            while out and not out[-1].strip():
                out.pop()
            for key, value in keys.items():
                out.extend([f"# {key}: calibration.ini", f"{key} = {value}"])
            out.append("")

    for line in lines:
        if (m := _SECTION.match(line)):
            flush(section)
            section = m.group(1).strip()
            out.append(line)
            continue
        k = _KEY.match(line)
        if section is not None and k and not line.lstrip().startswith(("#", ";")) and k.group(1) in pending.get(section, {}):
            # LinuxCNC has no comments after a value: the note goes above
            value = pending[section].pop(k.group(1))
            out.append(f"# {k.group(1)}: calibration.ini (machine.ini: {line.split('=', 1)[1].strip()})")
            out.append(f"{k.group(1)} = {value}")
            continue
        out.append(line)
    flush(section)
    for name, keys in pending.items():
        if keys:
            out.append(f"[{name}]")
            for key, value in keys.items():
                out.extend([f"# {key}: calibration.ini", f"{key} = {value}"])
            out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def calibrated_ini(ini: Path, payload: Mapping[str, Any]) -> Tuple[Path, List[str]]:
    """The INI LinuxCNC should start with: ``ini`` itself without a
    ``calibration.ini`` (or nothing in it for LinuxCNC), else
    ``machine.calibrated.ini`` next to it. Returns (path, the overridden
    ``SECTION.KEY`` names)."""
    calibration = CalibrationFile(calibration_path(ini.parent)).load()
    text = ini.read_text(encoding="utf-8")
    overrides = ini_overrides(calibration, payload, text)
    target = ini.parent / CALIBRATED_INI_NAME
    if not any(overrides.values()):
        if target.exists():
            target.unlink()
        return ini, []
    target.write_text(
        f"# Generated at machine start: {ini.name} + {FILE_NAME}. Do not edit — edit {ini.name} "
        f"(Generate) or the Calibration tab.\n" + merge_ini(text, overrides), encoding="utf-8")
    return target, [f"{s}.{k}" for s, keys in overrides.items() for k in keys]


# --------------------------------------------------------------------------- #
# hardware.json + [CALIBRATION] (machine backend)                               #
# --------------------------------------------------------------------------- #

def overlay_payload(payload: Dict[str, Any], values: Mapping[str, str]) -> Dict[str, Any]:
    """A copy of ``payload`` with the ``[CALIBRATION]`` values in place of
    the profile's (only where the machine has the feature)."""
    if not values:
        return payload
    out = copy.deepcopy(payload)

    def number(key: str) -> Optional[float]:
        try:
            return float(values[key]) if key in values else None
        except ValueError:
            return None

    z_offset = number(PROBE_Z_OFFSET)
    if z_offset is not None and isinstance(out.get("probe"), dict):
        out["probe"]["z_offset"] = z_offset
    flow = number(FLOW)
    if flow is not None:
        for tool in out.get("tools") or []:
            if isinstance(tool, dict) and tool.get("type") == "extruder":
                tool["flow"] = flow
    advance = number(PRESSURE_ADVANCE)
    if advance is not None:
        for tool in out.get("tools") or []:
            if isinstance(tool, dict) and tool.get("type") == "extruder":
                tool["pressure_advance"] = advance
    if isinstance(out.get("input_shaper"), dict):
        for axis in ("x", "y"):
            freq = number(SHAPER_FREQ.format(axis=axis.upper()))
            if freq is not None:
                out["input_shaper"][f"freq_{axis}"] = freq
            kind = values.get(SHAPER_TYPE.format(axis=axis.upper()))
            if kind:
                out["input_shaper"][f"type_{axis}"] = kind
    skew = number(SKEW_XY)
    if skew is not None and any(isinstance(out.get(k), dict) for k in ("input_shaper", "skew_correction", "adxl345")):
        out["skew_correction"] = {**(out.get("skew_correction") or {}), "xy_factor": skew}
    return out


__all__ = [
    "CALIBRATED_INI_NAME", "CalibrationFile", "FILE_NAME", "FLOW", "INPUT_SHAPER_SECTION", "PRESSURE_ADVANCE",
    "PROBE_Z_OFFSET", "SHAPER_FREQ", "SHAPER_TYPE", "SKEW_XY", "STATE", "VALUES", "calibrated_ini",
    "calibration_path", "ini_overrides", "merge_ini", "overlay_payload",
]
