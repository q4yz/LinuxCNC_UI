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

from core.calibration_file import (FLOW, INPUT_SHAPER_SECTION, PRESSURE_ADVANCE, RETRACT_LENGTH, RETRACT_SPEED, STALL, PROBE_Z_OFFSET, SHAPER_FREQ, SHAPER_TYPE,
                                   SKEW_XY, VALUES, CalibrationFile, calibration_path)
from exceptions import BadRequestError, ConflictError, NotFoundError
from models.machineconfig.HardwareRecords import HardwareRecords

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
    #: Guided calibrations: Start prints a test object (``print_test``),
    #: the operator measures it (``inputs``, the card's ``figure``) and
    #: ``submit`` computes, saves and applies the result.
    print_test: Optional[Callable[[Mapping[str, float]], str]] = None
    inputs: List[Param] = field(default_factory=list)
    submit: Optional[Callable[[Mapping[str, float]], str]] = None
    figure: str = ""


def _home_command(axis: str) -> Callable[[Mapping[str, float]], str]:
    return lambda p: f"G28 {axis}"


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
    from services.calibration.ShaperService import get_shaper_service

    get_shaper_service().set_shaper(axis, freq)
    for number in _axis_joints(axis):
        halcmd_setp(f"shape-j{number}.shaper-type", SHAPER_CODES.get(kind, 2))


def _axis_joints(axis: str) -> List[int]:
    """The joint numbers of ``axis`` (jointshape's ``shape-j<n>``)."""
    from services.machine.HardwareConfigService import HardwareConfigService

    for record_ in HardwareConfigService().load_payload().get("axes") or []:
        if str(record_.get("id", "")).lower() == axis.lower():
            return [int(n) for n in record_.get("joint_numbers") or []]
    return []


# -- the catalog ------------------------------------------------------------- #

class CalibrationService:
    def catalog(self) -> List[Calibration]:
        from services.motion.BedMeshProbeService import get_bed_mesh_probe_service
        from services.machine.HardwareConfigService import HardwareConfigService
        from services.motion import LevelingService
        from services.calibration.PidCalibrateService import get_pid_calibrate_service
        from services.motion.ProbeAccuracyService import get_probe_accuracy_service
        from services.calibration.ProbeCalibrateService import get_probe_calibrate_service
        from services.calibration.ResonanceService import get_resonance_service
        from services.calibration.ShaperService import get_shaper_service
        from services.motion.ZTiltService import get_z_tilt_service

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
                        # running = moving; the paper test between the moves
                        # is ``session`` (its buttons must stay usable)
                        running=calibrate.is_running,
                        values={"z_offset": (payload.get("probe") or {}).get("z_offset"),
                                **calibrate.snapshot()}),
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
            "Needs [adxl345] on a Remora machine (Cartesian or CoreXY: the jointshape component).",
            command=lambda p: "SHAPER_CALIBRATE", running=get_resonance_service().is_running,
            values={k: shaper.get(k) for k in ("freq_x", "type_x", "freq_y", "type_y")}))
        items.extend(guided_calibrations(payload))
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
                "guided": item.submit is not None, "figure": item.figure,
                "inputs": [p.__dict__ for p in item.inputs],
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
        if item.print_test is not None:
            return item.print_test(values)
        command = item.command(values)
        from services.machine.StateService import get_state_service

        get_state_service().run_mdi(command)
        return command

    def submit(self, calibration_id: str, measured: Mapping[str, float]) -> str:
        """A guided calibration's measurements -> its result (saved, applied)."""
        item = self.find(calibration_id)
        if item.submit is None:
            raise BadRequestError("This calibration measures by itself — no values to enter.")
        if not item.available:
            raise BadRequestError(item.reason)
        if not item.inputs:  # its own controls (sensorless homing): numbers as sent
            try:
                return item.submit({k: float(v) for k, v in measured.items()})
            except (TypeError, ValueError) as exc:
                raise BadRequestError("The values must be numbers.") from exc
        values = {}
        for p in item.inputs:
            raw = measured.get(p.name)
            try:
                value = float(raw)
            except (TypeError, ValueError) as exc:
                raise BadRequestError(f"{p.name}: enter a number.") from exc
            if (p.minimum is not None and value < p.minimum) or (p.maximum is not None and value > p.maximum):
                raise BadRequestError(f"{p.name} {value:g} is outside {p.minimum:g} … {p.maximum:g}.")
            values[p.name] = value
        return item.submit(values)

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
        elif item.kind == "skew":
            store.update({VALUES: {SKEW_XY: None}})
            from services.calibration.ShaperService import get_shaper_service

            get_shaper_service().set_skew(_profile_skew())
        elif item.kind == "flow":
            store.update({VALUES: {FLOW: None}})
            from services.program.PrintTuningService import get_print_tuning_service

            get_print_tuning_service().set_flow(100.0)
        elif item.kind == "extruder_steps":
            joint = item.values.get("joint")
            store.update({f"JOINT_{joint}": {"SCALE": None}})
        elif item.kind == "retraction":
            store.update({VALUES: {RETRACT_LENGTH: None, RETRACT_SPEED: None}})
        elif item.kind == "sensorless":
            store.update({VALUES: {STALL.format(joint=item.id[len("sensorless_"):].upper()): None}})
            store.set_state(item.id, low=None, high=None, loaded=None)
        elif item.kind == "pressure_advance":
            store.update({VALUES: {PRESSURE_ADVANCE: None}})
            from services.program.PrintTuningService import get_print_tuning_service

            get_print_tuning_service().set_pressure_advance(_profile_pressure_advance())
        else:
            raise BadRequestError("This calibration saves no value to clear.")
        store.set_state(calibration_id, result="cleared — the profile's values from the next start")


# -- guided calibrations: a test print, measured by hand ---------------------- #

TEST_PRINT_DIR = "calibration"


def _profile_skew() -> float:
    from services.machine.HardwareConfigService import HardwareConfigService

    return float((HardwareConfigService().load_payload().get("skew_correction") or {}).get("xy_factor") or 0.0)


def _profile_pressure_advance() -> float:
    from services.machine.HardwareConfigService import HardwareConfigService

    for tool in HardwareConfigService().load_payload().get("tools") or []:
        if isinstance(tool, dict) and tool.get("type") == "extruder":
            return float(tool.get("pressure_advance") or 0.0)
    return 0.0


def _heater_defaults(payload: Mapping[str, Any]) -> List[Param]:
    def limit(kind: str, default: float) -> float:
        tool = next((t for t in payload.get("tools") or [] if isinstance(t, dict) and t.get("type") == kind), {})
        return float(tool.get("max_temp") or default)

    return [Param("hotend", 210, "°C", 150, limit("extruder", 300)),
            Param("bed", 60, "°C", 0, limit("heated_bed", 120))]


def _printing(name: str) -> Callable[[], bool]:
    """The test print ``name`` is the program running now."""
    def check() -> bool:
        from hardware import get_stat_channel

        stat = get_stat_channel()
        if stat is None:
            return False
        try:
            stat.poll()
        except Exception:  # noqa: BLE001 - no LinuxCNC
            return False
        running = getattr(stat, "interp_state", 1) != 1
        return running and str(getattr(stat, "file", "") or "").endswith(f"{TEST_PRINT_DIR}/{name}.ngc")
    return check


def start_test_print(name: str, gcode: str) -> str:
    """Convert ``gcode`` into ``nc_files/calibration/<name>.ngc``, load and
    start it (its G28 runs first, as for an uploaded print)."""
    from domain_file_services.ProgramFileService import ProgramFileService
    from hardware import get_stat_channel
    from hardware.Connection import MachineState
    from services.program.ProgramService import get_program_lifecycle_service

    stat = get_stat_channel()
    if stat is None:
        raise BadRequestError("LinuxCNC is not running.")
    stat.poll()
    if stat.estop or stat.task_state != MachineState.ON.value:
        raise BadRequestError("Turn the machine on (and out of E-stop) first.")
    if getattr(stat, "interp_state", 1) != 1:
        raise ConflictError("A program or MDI command is running.")
    files = ProgramFileService()
    stored = files.save_upload(f"{TEST_PRINT_DIR}/{name}.gcode", gcode.encode("utf-8"))
    service = get_program_lifecycle_service()
    service.load_program(str(files.resolve_program_path(stored)))
    service.start_program()
    return f"test print {stored}"


def guided_calibrations(payload: Mapping[str, Any]) -> List[Calibration]:
    from core.calibration_prints import pa_result, pa_tower, settings_from_payload, skew_result, skew_square
    from services.calibration.ShaperService import get_shaper_service

    has_extruder = any(isinstance(t, dict) and t.get("type") == "extruder" for t in payload.get("tools") or [])
    no_extruder = "The profile has no [extruder]."
    heaters = _heater_defaults(payload)
    store = calibration_file()

    # skew: the factor in use while printing is part of the result
    def print_skew(p: Mapping[str, float]) -> str:
        text = skew_square(settings_from_payload(payload, p["hotend"], p["bed"]), size=p["size"])
        in_use = get_shaper_service().skew
        message = start_test_print("skew_square", text)
        store.set_state("skew", print_factor=f"{in_use:.8f}", print_size=f"{p['size']:g}")
        return message

    def submit_skew(m: Mapping[str, float]) -> str:
        state = store.state("skew")
        printed_with = float(state.get("print_factor") or get_shaper_service().skew)
        try:
            factor = skew_result(m["ac"], m["bd"], m["ad"], printed_with)
        except ValueError as exc:
            raise BadRequestError(f"These lengths are not a parallelogram: {exc}") from exc
        if abs(factor) > 0.2:
            raise BadRequestError(f"Skew factor {factor:.4f} is implausible — check the measurements.")
        result = f"factor {factor:.6f} (AC {m['ac']:g}, BD {m['bd']:g}, AD {m['ad']:g})"
        record("skew", result, {VALUES: {SKEW_XY: round(factor, 8)}})
        get_shaper_service().set_skew(factor)
        return result

    skew_available = get_shaper_service().available()
    side = Param("size", 100, "mm", 40, 200)
    skew = Calibration(
        "skew", "skew", "", skew_available,
        "Needs the jointshape component: add an empty [skew_correction] section to the profile (a Remora "
        "machine, Cartesian or CoreXY) and generate the machine.",
        params=heaters + [side],
        running=_printing("skew_square"),
        values={"factor": get_shaper_service().skew},
        print_test=print_skew, submit=submit_skew, figure="skew",
        inputs=[Param("ac", 141.42, "mm", 10, 400), Param("bd", 141.42, "mm", 10, 400), Param("ad", 100, "mm", 10, 300)],
    )

    # pressure advance: start / factor of the printed tower
    def print_pa(p: Mapping[str, float]) -> str:
        from services.program.PrintTuningService import get_print_tuning_service

        restore = get_print_tuning_service().state("", 0).pressure_advance
        text = pa_tower(settings_from_payload(payload, p["hotend"], p["bed"]), height=p["height"], start=p["start"],
                        factor=p["factor"], speed=p["speed"], restore=float(restore or 0.0))
        message = start_test_print("pressure_advance_tower", text)
        store.set_state("pressure_advance", print_start=f"{p['start']:g}", print_factor=f"{p['factor']:g}",
                        print_height=f"{p['height']:g}")
        return message

    def submit_pa(m: Mapping[str, float]) -> str:
        state = store.state("pressure_advance")
        try:
            start, factor = float(state["print_start"]), float(state["print_factor"])
        except (KeyError, ValueError) as exc:
            raise BadRequestError("Print the tower first: its start / factor are not known.") from exc
        height = m["height"]
        if height > float(state.get("print_height") or 1e9) + 1:
            raise BadRequestError(f"The tower is only {state.get('print_height')} mm tall.")
        k = pa_result(start, factor, height)
        result = f"K {k:.4f} (best at {height:g} mm, {start:g} + {factor:g}/mm)"
        record("pressure_advance", result, {VALUES: {PRESSURE_ADVANCE: k}})
        from services.program.PrintTuningService import get_print_tuning_service

        get_print_tuning_service().set_pressure_advance(k)
        return result

    from services.program.PrintTuningService import get_print_tuning_service

    advance = float(get_print_tuning_service().state("", 0).pressure_advance or 0.0)
    pa = Calibration(
        "pressure_advance", "pressure_advance", "", has_extruder, no_extruder,
        params=heaters + [Param("start", 0.0, "", 0, 1), Param("factor", 0.005, "/mm", 0.0005, 0.05),
                          Param("height", 40, "mm", 5, 100), Param("speed", 100, "mm/s", 20, 300)],
        running=_printing("pressure_advance_tower"),
        values={"advance": advance},
        print_test=print_pa, submit=submit_pa, figure="pressure_advance",
        inputs=[Param("height", 10, "mm", 0, 100)],
    )
    return [skew, pa, *_more_guided(payload, heaters, store)]


def ini_value(section: str, key: str) -> Optional[float]:
    """A number of the INI LinuxCNC runs with (``machine.calibrated.ini``:
    earlier calibrations included); ``None`` without LinuxCNC."""
    try:
        import linuxcnc

        from hardware import get_stat_channel

        stat = get_stat_channel()
        if stat is None:
            return None
        stat.poll()
        raw = linuxcnc.ini(stat.ini_filename).find(section, key)
        return float(raw) if raw is not None else None
    except Exception:  # noqa: BLE001 - no LinuxCNC / no such key
        return None


def _extruder(payload: Mapping[str, Any]) -> Dict[str, Any]:
    return next((t for t in payload.get("tools") or [] if isinstance(t, dict) and t.get("type") == "extruder"), {})


def _extruder_joint(payload: Mapping[str, Any]) -> Optional[int]:
    tool_id = _extruder(payload).get("id")
    for joint in payload.get("joints") or []:
        if isinstance(joint, dict) and joint.get("id") == tool_id and joint.get("joint_number") is not None:
            return int(joint["joint_number"])
    return None


def _z_joints(payload: Mapping[str, Any]) -> List[int]:
    for axis in payload.get("axes") or []:
        if str(axis.get("id", "")).lower() == "z":
            return [int(n) for n in axis.get("joint_numbers") or []]
    return []


def first_layer_target(payload: Mapping[str, Any]) -> str:
    """What sets the first layer's height: ``probe`` (its z_offset — Z homes
    on it, or the mesh holds absolute heights) or ``endstop`` (Z's switch,
    HOME_OFFSET)."""
    probe = isinstance(payload.get("probe"), dict) and bool(payload["probe"].get("pin"))
    if not probe:
        return "endstop"
    if isinstance(payload.get("z_virtual_endstop"), dict):
        return "probe"
    mesh = payload.get("bed_mesh")
    return "probe" if isinstance(mesh, dict) and not mesh.get("zero_reference_position") else "endstop"


def _more_guided(payload: Mapping[str, Any], heaters: List[Param], store: CalibrationFile) -> List[Calibration]:
    from core.calibration_prints import (extrude_test, first_layer_patches, first_layer_result, flow_cube,
                                         flow_result, settings_from_payload, steps_result)
    from services.program.PrintTuningService import get_print_tuning_service

    extruder = _extruder(payload)
    joint = _extruder_joint(payload)
    tuning = get_print_tuning_service()

    # -- extruder steps: [JOINT_n] SCALE --------------------------------- #
    def print_steps(p: Mapping[str, float]) -> str:
        text = extrude_test(settings_from_payload(payload, p["hotend"], 0), length=p["length"], speed=p["speed"])
        scale = ini_value(f"JOINT_{joint}", "SCALE")
        message = start_test_print("extrude_100", text)
        store.set_state("extruder_steps", print_length=f"{p['length']:g}",
                        print_scale="" if scale is None else f"{scale:.6f}")
        return message

    def submit_steps(m: Mapping[str, float]) -> str:
        state = store.state("extruder_steps")
        scale = _number(state.get("print_scale") or None, ini_value(f"JOINT_{joint}", "SCALE"))
        if not scale:
            raise BadRequestError("The extruder's SCALE is unknown — run the test with LinuxCNC running.")
        requested = float(state.get("print_length") or 100.0)
        extruded = m["mark"] - m["remaining"]
        try:
            new = steps_result(float(scale), requested, extruded)
        except ValueError as exc:
            raise BadRequestError(f"{exc} (mark {m['mark']:g} − remaining {m['remaining']:g} mm).") from exc
        if not 0.8 <= new / float(scale) <= 1.25:
            raise BadRequestError(f"{extruded:g} mm of {requested:g} mm is more than 20 % off — check the extruder "
                                  "(slipping, clogged, the mark) before calibrating it.")
        result = (f"SCALE {float(scale):.3f} → {new:.3f} steps/mm ({extruded:g} of {requested:g} mm; "
                  f"rotation_distance × {float(scale) / new:.4f}) — from the next LinuxCNC start")
        record("extruder_steps", result, {f"JOINT_{joint}": {"SCALE": round(new, 4)}})
        return result

    current_scale = ini_value(f"JOINT_{joint}", "SCALE") if joint is not None else None
    steps = Calibration(
        "extruder_steps", "extruder_steps", "", joint is not None,
        "The profile has no [extruder] with a motor.",
        params=[heaters[0], Param("length", 100, "mm", 20, 200), Param("speed", 1.0, "mm/s", 0.2, 5)],
        running=_printing("extrude_100"),
        values={"scale": current_scale, "joint": joint},
        print_test=print_steps, submit=submit_steps, figure="extruder_steps",
        inputs=[Param("mark", 120, "mm", 10, 400), Param("remaining", 20, "mm", 0, 400)],
    )

    # -- flow: [CALIBRATION] FLOW, the print tuning's flow at start -------- #
    def print_flow(p: Mapping[str, float]) -> str:
        settings = settings_from_payload(payload, p["hotend"], p["bed"])
        text = flow_cube(settings, size=p["size"])
        message = start_test_print("flow_cube", text)
        store.set_state("flow", print_flow=f"{tuning.flow:g}", print_width=f"{settings.width:g}")
        return message

    def submit_flow(m: Mapping[str, float]) -> str:
        state = store.state("flow")
        try:
            used, width = float(state["print_flow"]), float(state["print_width"])
        except (KeyError, ValueError) as exc:
            raise BadRequestError("Print the cube first: its flow / wall width are not known.") from exc
        new = flow_result(used, width, m["wall"])
        if not 70 <= new <= 130:
            raise BadRequestError(f"Flow {new:g} % is implausible — measure the wall again (one wall, not two).")
        result = f"flow {new:g} % (wall {m['wall']:g} mm, wanted {width:g} mm, printed at {used:g} %)"
        record("flow", result, {VALUES: {FLOW: new}})
        tuning.set_flow(new)
        return result

    flow = Calibration(
        "flow", "flow", "", bool(extruder), "The profile has no [extruder].",
        params=heaters + [Param("size", 30, "mm", 15, 80)],
        running=_printing("flow_cube"),
        values={"flow": tuning.flow},
        print_test=print_flow, submit=submit_flow, figure="flow",
        inputs=[Param("wall", 0.45, "mm", 0.1, 2)],
    )

    # -- first layer: the live Z offset into z_offset / HOME_OFFSET -------- #
    target = first_layer_target(payload)

    def print_first_layer(p: Mapping[str, float]) -> str:
        text = first_layer_patches(settings_from_payload(payload, p["hotend"], p["bed"]))
        return start_test_print("first_layer", text)

    def submit_first_layer(m: Mapping[str, float]) -> str:
        if _printing("first_layer")():
            raise ConflictError("Save once the print has finished.")
        live = tuning.z_offset
        if abs(live) < 1e-4:
            raise BadRequestError("The live Z offset is 0 — nothing to save.")
        if target == "probe":
            current = float((payload.get("probe") or {}).get("z_offset") or 0.0)
            new = first_layer_result(current, live)
            if new <= 0:
                raise BadRequestError(f"z_offset {new:g} would put the nozzle above the probe's trigger.")
            record("first_layer", f"live Z {live:+.3f} → z_offset {current:.3f} → {new:.3f} mm",
                   {VALUES: {PROBE_Z_OFFSET: new}})
            record("probe_z_offset", f"z_offset {new:.3f} mm (first layer)")
            what = f"z_offset {new:.3f} mm"
        else:
            joints = _z_joints(payload)
            values: Dict[str, Dict[str, Any]] = {}
            for n in joints:
                current = ini_value(f"JOINT_{n}", "HOME_OFFSET")
                if current is None:
                    raise BadRequestError("Z's HOME_OFFSET is unknown — save it with LinuxCNC running.")
                values[f"JOINT_{n}"] = {"HOME_OFFSET": first_layer_result(current, live)}
            record("first_layer", f"live Z {live:+.3f} → Z HOME_OFFSET "
                   + ", ".join(f"{v['HOME_OFFSET']:g}" for v in values.values()), values)
            what = "Z's home position"
        return (f"{what} saved (live Z {live:+.3f}). The live offset stays until LinuxCNC restarts; after the "
                "restart home again" + (" and probe the bed mesh again" if target == "probe" else "") + ".")

    first = Calibration(
        "first_layer", "first_layer", "", bool(extruder), "The profile has no [extruder].",
        params=heaters,
        running=_printing("first_layer"),
        values={"live_offset": tuning.z_offset, "target": target},
        print_test=print_first_layer, submit=submit_first_layer, figure="first_layer",
        inputs=[],
    )
    return [steps, flow, first, _retraction(payload, heaters, store), *_sensorless(payload, store)]


def _retraction(payload: Mapping[str, Any], heaters: List[Param], store: CalibrationFile) -> Calibration:
    """A tower pair with a growing retraction; saved as [firmware_retraction]
    retract_length (the G10 / G11 of files uploaded from then on)."""
    from core.calibration_prints import retraction_result, retraction_tower, settings_from_payload

    def print_retraction(p: Mapping[str, float]) -> str:
        text = retraction_tower(settings_from_payload(payload, p["hotend"], p["bed"]), start=p["start"],
                                factor=p["factor"], height=p["height"], speed=p["speed"])
        message = start_test_print("retraction_tower", text)
        store.set_state("retraction", print_start=f"{p['start']:g}", print_factor=f"{p['factor']:g}",
                        print_height=f"{p['height']:g}", print_speed=f"{p['speed']:g}")
        return message

    def submit_retraction(m: Mapping[str, float]) -> str:
        state = store.state("retraction")
        try:
            start, factor, speed = float(state["print_start"]), float(state["print_factor"]), float(state["print_speed"])
        except (KeyError, ValueError) as exc:
            raise BadRequestError("Print the towers first: their start / factor are not known.") from exc
        if m["height"] > float(state.get("print_height") or 1e9) + 1:
            raise BadRequestError(f"The towers are only {state.get('print_height')} mm tall.")
        length = retraction_result(start, factor, m["height"])
        result = f"retract {length:g} mm at {speed:g} mm/s (no strings from {m['height']:g} mm)"
        record("retraction", result, {VALUES: {RETRACT_LENGTH: length, RETRACT_SPEED: speed}})
        return (result + " — used for the G10 / G11 of files uploaded from now on (slicer: firmware retraction); "
                "upload earlier files again.")

    current = HardwareRecords.firmware_retraction(payload)
    return Calibration(
        "retraction", "retraction", "", bool(_extruder(payload)), "The profile has no [extruder].",
        params=heaters + [Param("start", 0.0, "mm", 0, 10), Param("factor", 0.05, "/mm", 0.005, 0.5),
                          Param("height", 30, "mm", 5, 80), Param("speed", 35, "mm/s", 10, 120)],
        running=_printing("retraction_tower"),
        values={"length": current.retract_length if current else None, "speed": current.retract_speed if current else None},
        print_test=print_retraction, submit=submit_retraction, figure="retraction",
        inputs=[Param("height", 10, "mm", 0, 80)],
    )


def _sensorless(payload: Mapping[str, Any], store: CalibrationFile) -> List[Calibration]:
    """One card per joint homed by StallGuard (``[tmc2209] diag_pin`` +
    ``driver_SGTHRS``): try a threshold (it reaches the board at the next
    LinuxCNC start), home, say how it went; halving the range each time."""
    from services.motion.HomingRoutineService import get_homing_routine_service

    drivers = {d.get("id"): d for d in payload.get("drivers") or [] if isinstance(d, dict)}
    axis_of = {int(n): str(a.get("id", "")).upper() for a in payload.get("axes") or []
               for n in a.get("joint_numbers") or []}
    homing = get_homing_routine_service()
    items = []
    for joint in payload.get("joints") or []:
        driver = drivers.get(joint.get("driver")) if isinstance(joint, dict) else None
        if not driver or not driver.get("diag_pin") or driver.get("stall_sensitivity") is None:
            continue
        joint_id = str(joint["id"]).lower()
        cid = f"sensorless_{joint_id}"
        axis = axis_of.get(int(joint.get("joint_number") or 0), joint_id)
        key = STALL.format(joint=joint_id.upper())
        profile = int(driver["stall_sensitivity"])

        def submit(m: Mapping[str, float], cid: str = cid, key: str = key, profile: int = profile,
                   axis: str = axis) -> str:
            state = store.state(cid)
            saved = store.values().get(key)
            loaded = int(float(state.get("loaded") or saved or profile))
            if "threshold" in m:
                value = int(round(m["threshold"]))
                if not 1 <= value <= 255:
                    raise BadRequestError("The threshold is 1 … 255.")
                store.update({VALUES: {key: value}})
                return f"{axis}: threshold {value} saved — restart LinuxCNC to load it into the driver, then home {axis}."
            verdict = int(m.get("verdict", 99))
            if verdict not in (-1, 0, 1):
                raise BadRequestError("verdict: -1 (stopped early), 1 (did not stop), 0 (good).")
            if verdict == 0:
                record(cid, f"{axis}: threshold {loaded} homes cleanly", {VALUES: {key: loaded}})
                store.set_state(cid, low=None, high=None)
                return f"{axis}: threshold {loaded} kept."
            low, high = int(state.get("low") or 0), int(state.get("high") or 256)
            if verdict < 0:
                high = loaded   # stopped early: too sensitive
            else:
                low = loaded    # ground at the end: not sensitive enough
            if high - low <= 1:
                raise BadRequestError(f"No threshold between {low} and {high} left — check the wiring / homing speed.")
            store.set_state(cid, low=low, high=high)
            suggestion = (low + high) // 2
            return f"{axis}: try {suggestion} (between {low} and {high})."

        state = store.state(cid)
        saved = store.values().get(key)
        low, high = int(state.get("low") or 0), int(state.get("high") or 256)
        loaded = state.get("loaded")
        items.append(Calibration(
            cid, "sensorless", axis, True,
            command=_home_command(axis),
            running=homing.is_running,
            values={"profile": profile, "saved": int(float(saved)) if saved else None,
                    "loaded": int(float(loaded)) if loaded else (None if saved else profile),
                    "low": low, "high": high, "suggestion": (low + high) // 2},
            submit=submit, figure="",
        ))
    return items


_SERVICE: Optional[CalibrationService] = None


def get_calibration_service() -> CalibrationService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = CalibrationService()
    return _SERVICE


__all__ = ["CalibrationService", "get_calibration_service", "halcmd_setp", "record", "record_input_shaper",
           "record_pid", "record_probe_z_offset"]
