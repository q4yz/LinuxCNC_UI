"""The Calibration tab: the machine's calibrations, their last result and
reminder, and what saving a result does (``calibration.ini``,
``core.calibration_file``).

Each automatic calibration's service calls :func:`record` when it
finishes: the time, a one-line result and — where it produces one — the
value, written to ``calibration.ini`` and applied right away where that
is possible:

==================  ===============================  ==========================
id                  saved                            applied now
==================  ===============================  ==========================
bed_mesh            (the mesh file, as before)       yes
z_tilt              (the motor offsets, as before)   yes
probe_accuracy      —                                —
probe_z_offset      [CALIBRATION] PROBE_Z_OFFSET     probing; Z homing on the
                                                     probe after a restart
pid_<heater>        [<HEATER>] PID_KP / KI / KD      PID-<heater>.KP … (halcmd)
input_shaper        [CALIBRATION] SHAPER_FREQ_X …,   frequency; type (halcmd)
                    [INPUT_SHAPER] TYPE_X …
==================  ===============================  ==========================
"""
from __future__ import annotations

import datetime as _dt
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional

from core.calibration_file import (INPUT_SHAPER_SECTION, PROBE_Z_OFFSET, SHAPER_FREQ, SHAPER_TYPE, VALUES,
                                   CalibrationFile, calibration_path)
from exceptions import BadRequestError, ConflictError, NotFoundError

logger = logging.getLogger("backend.services.calibration")

#: jointshape's shaper-type codes.
SHAPER_CODES = {"zv": 1, "mzv": 2, "zvd": 3, "ei": 4}
#: PID_CALIBRATE's default target per heater type.
DEFAULT_PID_TARGET = {"extruder": 210.0, "heated_bed": 60.0}


@dataclass
class Param:
    name: str
    default: float
    unit: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None


@dataclass
class Calibration:
    id: str
    kind: str                     # bed_mesh, z_tilt, probe_accuracy, probe_z_offset, pid, input_shaper
    label: str                    # e.g. the heater's id for pid
    available: bool
    reason: str = ""              # why not available
    params: List[Param] = field(default_factory=list)
    command: Callable[[Mapping[str, float]], str] = lambda p: ""
    running: Callable[[], bool] = lambda: False
    values: Dict[str, Any] = field(default_factory=dict)


def _pid_command(heater_id: str) -> Callable[[Mapping[str, float]], str]:
    return lambda p: f"PID_CALIBRATE HEATER={heater_id} TARGET={p['target']:g}"


def calibration_file() -> CalibrationFile:
    from domain_file_services.paths import default_machine_hardware_json

    return CalibrationFile(calibration_path(default_machine_hardware_json().parent))


def _now() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def _today() -> _dt.date:
    return _dt.date.today()


def halcmd_setp(name: str, value: Any) -> bool:
    """``halcmd setp <name> <value>`` on the running HAL (best effort: a
    value that cannot be set now still applies at the next start)."""
    if shutil.which("halcmd") is None:
        return False
    try:
        result = subprocess.run(["halcmd", "setp", name, str(value)], capture_output=True, text=True, timeout=5,
                                stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("halcmd setp %s %s: %s", name, value, exc)
        return False
    if result.returncode != 0:
        logger.warning("halcmd setp %s %s: %s", name, value, (result.stderr or result.stdout).strip())
    return result.returncode == 0


def record(calibration_id: str, result: str, values: Optional[Mapping[str, Mapping[str, Any]]] = None) -> None:
    """A calibration finished: its time and result, ``values`` saved to
    ``calibration.ini``; a reminder that was due is done."""
    try:
        store = calibration_file()
        if not store.path.parent.is_dir():
            return  # no machine generated / selected: nothing to keep it in
        if values:
            store.update(values)
        state = store.state(calibration_id)
        remind = state.get("remind")
        done = remind is not None and _due(remind)
        store.set_state(calibration_id, last=_now(), result=result, remind=None if done else remind)
    except OSError as exc:
        logger.warning("calibration.ini: cannot record %s: %s", calibration_id, exc)


def _number(raw: Optional[str], fallback: Any) -> Any:
    try:
        return float(raw) if raw is not None else fallback
    except ValueError:
        return fallback


def _due(remind: str) -> bool:
    try:
        return _dt.date.fromisoformat(remind[:10]) <= _today()
    except ValueError:
        return False


# -- results with values ------------------------------------------------------ #

def record_pid(heater_id: str, kp: float, ki: float, kd: float) -> None:
    from mappers.machineconfig import heater_ini_section

    section = heater_ini_section(heater_id)
    record(f"pid_{heater_id}", f"Kp {kp:.3f}  Ki {ki:.3f}  Kd {kd:.3f}",
           {section: {"PID_KP": round(kp, 4), "PID_KI": round(ki, 4), "PID_KD": round(kd, 4)}})
    for pin, value in (("KP", kp), ("KI", ki), ("KD", kd)):
        halcmd_setp(f"PID-{heater_id}.{pin}", f"{value:.4f}")


def record_probe_z_offset(z_offset: float) -> None:
    record("probe_z_offset", f"z_offset {z_offset:.3f} mm", {VALUES: {PROBE_Z_OFFSET: round(z_offset, 4)}})


def record_input_shaper(axis: str, kind: str, freq: float, vibrations: float) -> None:
    """One axis of SHAPER_CALIBRATE; the result line keeps both axes."""
    axis_u = axis.upper()
    store = calibration_file()
    values = store.values()
    values[SHAPER_FREQ.format(axis=axis_u)] = f"{freq:.1f}"
    values[SHAPER_TYPE.format(axis=axis_u)] = kind
    parts = []
    for a in ("X", "Y"):
        f, k = values.get(SHAPER_FREQ.format(axis=a)), values.get(SHAPER_TYPE.format(axis=a))
        if f and k:
            parts.append(f"{a} {k} {float(f):.1f} Hz")
    record("input_shaper", ", ".join(parts) + f" ({vibrations * 100:.0f} % vibration left on {axis_u})", {
        VALUES: {SHAPER_FREQ.format(axis=axis_u): round(freq, 1), SHAPER_TYPE.format(axis=axis_u): kind},
        INPUT_SHAPER_SECTION: {f"TYPE_{axis_u}": SHAPER_CODES.get(kind, 2)},
    })
    from services.ShaperService import get_shaper_service

    get_shaper_service().set_shaper(axis, freq)
    for number in _axis_joints(axis):
        halcmd_setp(f"shape-j{number}.shaper-type", SHAPER_CODES.get(kind, 2))


def _axis_joints(axis: str) -> List[int]:
    """The joint numbers of ``axis`` (jointshape's ``shape-j<n>``)."""
    from services.HardwareConfigService import HardwareConfigService

    for record_ in HardwareConfigService().load_payload().get("axes") or []:
        if str(record_.get("id", "")).lower() == axis.lower():
            return [int(n) for n in record_.get("joint_numbers") or []]
    return []


# -- the catalog ------------------------------------------------------------- #

class CalibrationService:
    def catalog(self) -> List[Calibration]:
        from services.BedMeshProbeService import get_bed_mesh_probe_service
        from services.HardwareConfigService import HardwareConfigService
        from services import LevelingService
        from services.PidCalibrateService import get_pid_calibrate_service
        from services.ProbeAccuracyService import get_probe_accuracy_service
        from services.ProbeCalibrateService import get_probe_calibrate_service
        from services.ResonanceService import get_resonance_service
        from services.ShaperService import get_shaper_service
        from services.ZTiltService import get_z_tilt_service

        payload = HardwareConfigService().load_payload()
        probe = isinstance(payload.get("probe"), dict) and bool(payload["probe"].get("pin"))
        no_probe = "The profile has no [probe]."
        mesh = get_bed_mesh_probe_service()
        calibrate = get_probe_calibrate_service()
        items = [
            Calibration("bed_mesh", "bed_mesh", "", isinstance(payload.get("bed_mesh"), dict) and probe,
                        "The profile has no [bed_mesh] (and [probe]).",
                        command=lambda p: "BED_MESH_CALIBRATE",
                        running=lambda: mesh.is_running() or LevelingService.is_running()),
            Calibration("z_tilt", "z_tilt", "", isinstance(payload.get("z_tilt"), dict) and probe,
                        "The profile has no [z_tilt] (and [probe]).",
                        command=lambda p: "Z_TILT_ADJUST", running=get_z_tilt_service().is_running),
            Calibration("probe_accuracy", "probe_accuracy", "", probe, no_probe,
                        params=[Param("samples", 10, "", 2, 100)],
                        command=lambda p: f"PROBE_ACCURACY SAMPLES={int(p['samples'])}",
                        running=get_probe_accuracy_service().is_running),
            Calibration("probe_z_offset", "probe_z_offset", "", probe, no_probe,
                        command=lambda p: "PROBE_CALIBRATE",
                        running=lambda: calibrate.is_running() or calibrate.session is not None,
                        values={"z_offset": (payload.get("probe") or {}).get("z_offset"),
                                "session": calibrate.session is not None}),
        ]
        from mappers.machineconfig import heater_ini_section

        saved = calibration_file().load()
        pid = get_pid_calibrate_service()
        for heater in pid._heaters():
            hid = str(heater["id"])
            gains = saved.get(heater_ini_section(hid), {})
            target = DEFAULT_PID_TARGET.get(str(heater.get("type")), 60.0)
            items.append(Calibration(
                f"pid_{hid}", "pid", hid, True,
                params=[Param("target", target, "°C", 30, float(heater.get("max_temp") or 300) - 5)],
                command=_pid_command(hid),
                running=pid.is_running,
                values={k: _number(gains.get(f"PID_{k.upper()}"), heater.get(f"pid_{k}")) for k in ("kp", "ki", "kd")}
                | {"calibrated": bool(gains)}))
        shaper = payload.get("input_shaper") if isinstance(payload.get("input_shaper"), dict) else {}
        has_adxl = isinstance(payload.get("adxl345"), dict)
        items.append(Calibration(
            "input_shaper", "input_shaper", "", has_adxl and get_shaper_service().available(),
            "Needs [adxl345] and a Cartesian Remora machine (the jointshape component).",
            command=lambda p: "SHAPER_CALIBRATE", running=get_resonance_service().is_running,
            values={k: shaper.get(k) for k in ("freq_x", "type_x", "freq_y", "type_y")}))
        return items

    def find(self, calibration_id: str) -> Calibration:
        for item in self.catalog():
            if item.id == calibration_id:
                return item
        raise NotFoundError(f"No calibration {calibration_id!r} on this machine.")

    def listing(self) -> Dict[str, Any]:
        store = calibration_file()
        out = []
        for item in self.catalog():
            state = store.state(item.id)
            remind = state.get("remind")
            out.append({
                "id": item.id, "kind": item.kind, "label": item.label, "available": item.available,
                "reason": "" if item.available else item.reason, "running": bool(item.available and item.running()),
                "last_tested": state.get("last"), "result": state.get("result"), "remind_at": remind,
                "due": bool(remind and _due(remind)),
                "params": [p.__dict__ for p in item.params], "values": item.values,
            })
        return {"items": out, "due": sum(1 for i in out if i["due"] and i["available"])}

    def start(self, calibration_id: str, params: Mapping[str, float]) -> str:
        item = self.find(calibration_id)
        if not item.available:
            raise BadRequestError(item.reason)
        if item.running():
            raise ConflictError("It is already running.")
        values: Dict[str, float] = {}
        for p in item.params:
            raw = params.get(p.name, p.default)
            try:
                value = float(raw)
            except (TypeError, ValueError) as exc:
                raise BadRequestError(f"{p.name}: {raw!r} is not a number.") from exc
            if (p.minimum is not None and value < p.minimum) or (p.maximum is not None and value > p.maximum):
                raise BadRequestError(f"{p.name} {value:g} is outside {p.minimum:g} … {p.maximum:g}.")
            values[p.name] = value
        command = item.command(values)
        from services.StateService import get_state_service

        get_state_service().run_mdi(command)
        return command

    @staticmethod
    def set_reminder(calibration_id: str, remind_at: Optional[str]) -> None:
        if remind_at:
            try:
                _dt.date.fromisoformat(remind_at[:10])
            except ValueError as exc:
                raise BadRequestError(f"{remind_at!r} is not a date (YYYY-MM-DD).") from exc
        calibration_file().set_state(calibration_id, remind=remind_at[:10] if remind_at else None)

    def clear(self, calibration_id: str) -> None:
        """Back to the profile's values (from the next start / now for the
        UI's values); the history stays."""
        from mappers.machineconfig import heater_ini_section

        item = self.find(calibration_id)
        store = calibration_file()
        if item.kind == "probe_z_offset":
            store.update({VALUES: {PROBE_Z_OFFSET: None}})
        elif item.kind == "pid":
            store.update({heater_ini_section(item.label): {"PID_KP": None, "PID_KI": None, "PID_KD": None}})
        elif item.kind == "input_shaper":
            store.update({VALUES: {SHAPER_FREQ.format(axis=a): None for a in "XY"}
                          | {SHAPER_TYPE.format(axis=a): None for a in "XY"},
                          INPUT_SHAPER_SECTION: {"TYPE_X": None, "TYPE_Y": None}})
        else:
            raise BadRequestError("This calibration saves no value to clear.")
        store.set_state(calibration_id, result="cleared — the profile's values from the next start")


_SERVICE: Optional[CalibrationService] = None


def get_calibration_service() -> CalibrationService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = CalibrationService()
    return _SERVICE


__all__ = ["CalibrationService", "get_calibration_service", "halcmd_setp", "record", "record_input_shaper",
           "record_pid", "record_probe_z_offset"]
