"""Probing a bed mesh — Klipper's ``BED_MESH_CALIBRATE``
(`.agent/component/bed_mesh.md` § 5).

``probe_count`` points over ``mesh_min`` ... ``mesh_max`` (a zig-zag,
row by row), each probed like a Z tilt point (``services.motion.Probing``),
with compensation switched off so its Z offset does not shift the
readings. The heights are saved as ``bed_meshes/<profile>.txt`` (less
the height at ``zero_reference_position``, when set), made the active
mesh, and compensation is switched back on — the component reloads the
active file then.

Runs as a ``BED_MESH_CALIBRATE [PROFILE=<name>]`` line (MDI, a macro,
the homing routine), ``POST /api/v1/bedmesh/calibrate``, or a print's
``G29`` (``LevelingService``). X, Y and Z must be homed.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional

from core.bed_mesh_file import write_mesh
from domain_file_services import paths
from exceptions import BadRequestError, ConflictError
from hardware import get_stat_channel
from hardware.Connection import MachineState, read_hal_pin
from services.motion.BedMeshService import get_bed_mesh_service
from services.machine.ConsoleLogger import LogLevel, get_console_logger
from services.machine.HardwareConfigService import HardwareConfigService
from services.motion.Probing import ProbeError, ProbeLatch, ProbeOffsets, ProbeSettings, probe_points

logger = logging.getLogger("backend.services.motion.BedMeshProbeService")

COMMAND = "BED_MESH_CALIBRATE"
DEFAULT_PROFILE = "default"
_PROFILE = re.compile(r"PROFILE\s*=\s*(\S+)", re.IGNORECASE)
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
#: How long compensation may take to ramp its Z offset back to 0.
OFFSET_SETTLE_S = 10.0


class BedMeshError(RuntimeError):
    """Why probing the mesh stopped."""


def parse_command(line: str) -> Optional[str]:
    """``BED_MESH_CALIBRATE [PROFILE=x]`` -> the profile name; ``None``
    for any other line."""
    code = line.split(";", 1)[0].strip()
    if not code.upper().startswith(COMMAND) or (len(code) > len(COMMAND) and not code[len(COMMAND)].isspace()):
        return None
    match = _PROFILE.search(code)
    name = match.group(1) if match else DEFAULT_PROFILE
    if not _NAME.fullmatch(name):
        raise BadRequestError(f"{COMMAND}: invalid PROFILE {name!r} (letters, digits, '_', '-', '.').")
    return name


def parse_adaptive(line: str) -> bool:
    """``BED_MESH_CALIBRATE ADAPTIVE=1``: probe only the loaded print's area."""
    match = re.search(r"\bADAPTIVE\s*=\s*(\S+)", line.split(";", 1)[0], re.IGNORECASE)
    return match is not None and match.group(1).lower() not in ("0", "false")


def adaptive_area(settings: Dict[str, Any], bounds: tuple[float, float, float, float]) -> Dict[str, Any]:
    """``settings`` with mesh_min / mesh_max shrunk to the print's area plus
    ``adaptive_margin``, inside the configured mesh; at least 1 mm wide."""
    margin = float(settings.get("adaptive_margin") or 0.0)
    (x0, y0), (x1, y1) = settings["mesh_min"], settings["mesh_max"]
    lo_x = min(max(float(x0), bounds[0] - margin), float(x1) - 1.0)
    lo_y = min(max(float(y0), bounds[1] - margin), float(y1) - 1.0)
    hi_x = max(min(float(x1), bounds[2] + margin), lo_x + 1.0)
    hi_y = max(min(float(y1), bounds[3] + margin), lo_y + 1.0)
    return {**settings, "mesh_min": [lo_x, lo_y], "mesh_max": [hi_x, hi_y]}


def grid(settings: Dict[str, Any]) -> tuple[List[float], List[float]]:
    """The mesh's X and Y coordinates."""
    (x0, y0), (x1, y1) = settings["mesh_min"], settings["mesh_max"]
    nx, ny = (int(n) for n in settings.get("probe_count") or [3, 3])
    xs = [float(x0) + i * (float(x1) - float(x0)) / (nx - 1) for i in range(nx)]
    ys = [float(y0) + i * (float(y1) - float(y0)) / (ny - 1) for i in range(ny)]
    return xs, ys


def zigzag(xs: List[float], ys: List[float]) -> List[tuple[int, int]]:
    """``(row, col)`` in probing order: rows alternate direction."""
    order: List[tuple[int, int]] = []
    for row in range(len(ys)):
        cols = range(len(xs)) if row % 2 == 0 else range(len(xs) - 1, -1, -1)
        order.extend((row, col) for col in cols)
    return order


def bilinear(xs: List[float], ys: List[float], z: List[List[float]], x: float, y: float) -> float:
    """The mesh height at ``(x, y)`` (clamped to the mesh)."""
    def locate(values: List[float], v: float) -> tuple[int, float]:
        v = min(max(v, values[0]), values[-1])
        i = max(0, min(len(values) - 2, next((k for k in range(len(values) - 1) if v <= values[k + 1]), len(values) - 2)))
        span = values[i + 1] - values[i]
        return i, (v - values[i]) / span if span else 0.0

    c, tx = locate(xs, x)
    r, ty = locate(ys, y)
    top = z[r][c] * (1 - tx) + z[r][c + 1] * tx
    bottom = z[r + 1][c] * (1 - tx) + z[r + 1][c + 1] * tx
    return top * (1 - ty) + bottom * ty


class BedMeshProbeService:
    def __init__(self, config: Optional[HardwareConfigService] = None) -> None:
        self._config = config or HardwareConfigService()
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def settings(self) -> Optional[Dict[str, Any]]:
        value = self._config.load_payload().get("bed_mesh")
        return value if isinstance(value, dict) and value.get("mesh_min") and value.get("mesh_max") else None

    def is_running(self) -> bool:
        worker = self._worker
        return worker is not None and worker.is_alive()

    def join(self, timeout: Optional[float] = None) -> None:
        worker = self._worker
        if worker is not None:
            worker.join(timeout)

    def start(self, profile: str = DEFAULT_PROFILE, busy: bool = False, adaptive: bool = False) -> None:
        """Check and probe on a worker thread (the endpoint, MDI)."""
        settings = self._require_settings()
        self._check_machine(get_stat_channel())
        if busy:
            raise ConflictError("A macro, the homing routine or Z tilt is running.")
        with self._lock:
            if self.is_running():
                raise ConflictError("The bed mesh is already being probed.")
            self._worker = threading.Thread(target=self._run_worker, args=(profile, adaptive), name="bed-mesh",
                                            daemon=True)
            self._worker.start()
        del settings  # checked above, read again by run()

    def _run_worker(self, profile: str, adaptive: bool = False) -> None:
        try:
            self.run(get_stat_channel(), profile, adaptive)
        except BedMeshError as exc:
            get_console_logger().log_event(f"{COMMAND} aborted: {exc}", level=LogLevel.ERROR, source="CMD")
        except Exception as exc:  # noqa: BLE001 - report, don't die silently
            logger.exception("Bed mesh probing crashed: %s", exc)
            get_console_logger().log_event(f"{COMMAND} aborted: {exc}", level=LogLevel.ERROR, source="CMD")

    def run(self, stat: Any, profile: str = DEFAULT_PROFILE, adaptive: bool = False) -> str:
        """Probe, save, activate, switch compensation on — on the calling
        (worker) thread. Returns the mesh name; raises :class:`BedMeshError`.
        ``adaptive``: only the loaded print's area (its bounds header)."""
        settings = self._require_settings()
        self._check_machine(stat)
        console = get_console_logger()
        if adaptive:
            settings = self._adaptive_settings(stat, settings, console)
        xs, ys = grid(settings)
        order = zigzag(xs, ys)
        points = [(xs[col], ys[row]) for row, col in order]
        console.log_event(f"{COMMAND}: probing {len(xs)} x {len(ys)} points.", level=LogLevel.DEBUG, source="CMD")

        def measured(k: int, height: float) -> None:
            x, y = points[k]
            console.log_event(
                f"{COMMAND}: point {k + 1}/{len(points)} X{x:g} Y{y:g} -> Z {height:.4f}",
                level=LogLevel.DEBUG, source="CMD",
            )
        compensation = get_bed_mesh_service()
        was_on = compensation.is_enabled()
        compensation.set_enabled(False)
        try:
            self._wait_offset_zero()
        except BedMeshError:
            if was_on:
                compensation.set_enabled(True)
            raise
        try:
            heights = probe_points(
                stat, points,
                safe_z=float(settings.get("horizontal_move_z") or 5.0),
                travel_mm_s=float(settings.get("speed") or 50.0),
                probe_mm_s=float(settings.get("probe_speed") or 5.0),
                bottom=float(settings.get("probe_min_z") or 0.0),
                progress=measured,
                offsets=ProbeOffsets.from_payload(self._config.load_payload()),
                settings=ProbeSettings.from_payload(self._config.load_payload()),
                latch=ProbeLatch.from_payload(self._config.load_payload()),
            )
        except ProbeError as exc:
            if was_on:
                compensation.set_enabled(True)
            raise BedMeshError(str(exc)) from exc
        z = [[0.0] * len(xs) for _ in ys]
        for (row, col), height in zip(order, heights):
            z[row][col] = height
        reference = settings.get("zero_reference_position")
        if reference:
            zero = bilinear(xs, ys, z, float(reference[0]), float(reference[1]))
            z = [[v - zero for v in row] for row in z]
            console.log_event(
                f"{COMMAND}: zero reference X{float(reference[0]):g} Y{float(reference[1]):g} at Z {zero:.4f}, "
                "subtracted from every point.",
                level=LogLevel.DEBUG, source="CMD",
            )
        for row_index, row in enumerate(z):
            console.log_event(
                f"{COMMAND}: row Y{ys[row_index]:g}: " + " ".join(f"{v:+.4f}" for v in row),
                level=LogLevel.DEBUG, source="CMD",
            )
        write_mesh(profile, xs, ys, z, paths.BED_MESHES_DIR, paths.ACTIVE_BED_MESH_FILE)
        compensation.set_enabled(True)  # reloads the active mesh
        flat = [v for row in z for v in row]
        from services.calibration.CalibrationService import record

        record("bed_mesh", f"{len(xs)} × {len(ys)}{' adaptive' if adaptive else ''}, range "
                           f"{max(flat) - min(flat):.3f} mm ('{profile}')")
        console.log_event(
            f"{COMMAND}: mesh '{profile}' saved and active, range {min(flat):+.3f} ... {max(flat):+.3f} mm.",
            level=LogLevel.INFO, source="CMD",
        )
        return profile

    def run_command(self, line: str, stat: Any) -> bool:
        """A ``BED_MESH_CALIBRATE`` line on the calling worker (a macro,
        the homing routine): probe and ``True``; ``False`` for another line."""
        profile = parse_command(line)
        if profile is None:
            return False
        self.run(stat, profile, parse_adaptive(line))
        return True

    @staticmethod
    def _adaptive_settings(stat: Any, settings: Dict[str, Any], console: Any) -> Dict[str, Any]:
        """The mesh over the loaded print's area (``read_bounds``), or the
        whole mesh when the file has none."""
        from core.gcode_converter import read_bounds

        path = str(getattr(stat, "file", "") or "")
        bounds = None
        if path:
            try:
                with open(path, encoding="utf-8", errors="ignore") as fp:
                    bounds = read_bounds("".join(fp.readline() for _ in range(6)))
            except OSError:
                bounds = None
        if bounds is None:
            console.log_event(f"{COMMAND} ADAPTIVE: the loaded program names no print area — the whole mesh.",
                              level=LogLevel.INFO, source="CMD")
            return settings
        area = adaptive_area(settings, bounds)
        console.log_event(
            f"{COMMAND} ADAPTIVE: the print's area X{area['mesh_min'][0]:g}..{area['mesh_max'][0]:g} "
            f"Y{area['mesh_min'][1]:g}..{area['mesh_max'][1]:g}.", level=LogLevel.DEBUG, source="CMD")
        return area

    # -- checks ----------------------------------------------------------- #

    def _require_settings(self) -> Dict[str, Any]:
        settings = self.settings()
        if settings is None:
            raise BadRequestError("This machine has no [bed_mesh] section (regenerate it for probing).")
        return settings

    def _check_machine(self, stat: Any) -> None:
        if stat is None:
            raise BadRequestError(f"Cannot run {COMMAND}: LinuxCNC is not running.")
        stat.poll()
        if stat.estop:
            raise BadRequestError(f"Cannot run {COMMAND} while the machine is in E-STOP.")
        if stat.task_state != MachineState.ON.value:
            raise BadRequestError(f"Turn the machine on before {COMMAND}.")
        homed = list(getattr(stat, "homed", ()) or ())
        needed = sorted({int(j) for a in self._config.get_axes() if str(a.get("id", "")).lower() in "xyz"
                         for j in a.get("joint_numbers") or []})
        missing = [j for j in needed if not (j < len(homed) and homed[j])]
        if missing:
            raise BadRequestError(f"Home X, Y and Z first (joint(s) {', '.join(map(str, missing))} not homed).")

    @staticmethod
    def _wait_offset_zero() -> None:
        """Compensation ramps its Z offset back to 0 after "off" (the live Z
        offset, also in axis.z.eoffset, stays)."""
        from services.program.PrintTuningService import get_print_tuning_service

        deadline = time.monotonic() + OFFSET_SETTLE_S
        while time.monotonic() < deadline:
            value = read_hal_pin("axis.z.eoffset")
            if value is None or abs(float(value) - get_print_tuning_service().z_offset) < 1e-4:
                return
            time.sleep(0.1)
        raise BedMeshError("compensation's Z offset did not return to 0 after switching it off.")


_SERVICE: Optional[BedMeshProbeService] = None


def get_bed_mesh_probe_service() -> BedMeshProbeService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = BedMeshProbeService()
    return _SERVICE


__all__ = ["COMMAND", "BedMeshError", "BedMeshProbeService", "get_bed_mesh_probe_service", "parse_command"]
