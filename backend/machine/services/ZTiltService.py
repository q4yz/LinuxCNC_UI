"""Z tilt adjust — level a Z axis driven by several motors
(`.agent/component/z_tilt.md` § 4).

One round: lift to ``horizontal_move_z``, probe every point
(``G53 G38.2`` down to ``probe_min_z``, the height from
``stat.probed_position``), fit a plane (``core.z_tilt``), move each Z
motor by the plane's height at its pivot minus the mean of those
heights. The move is a per-motor HAL offset (``ZTiltHalMapper``): this
service writes the target to ``webgui.ztilt-<k>``, a ``limit2`` ramps it
in. With ``retries`` it probes again until the probed heights differ by
no more than ``retry_tolerance``; a spread that grows means the pivots
do not match the motors and stops it.

Runs as ``POST /api/v1/ztilt/adjust`` (its own worker), or as a
``Z_TILT_ADJUST`` line inside a macro or the homing routine (that
worker). Re-home Z afterwards (``G28 Z`` in the routine) if Z homes on
the probe: the mean height is kept, the reference point is not.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from core.z_tilt import motor_adjustments
from dtos.pins.HalPin import HalDataType
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from exceptions import BadRequestError, ConflictError
from hardware import get_stat_channel
from hardware.Connection import MachineState, read_hal_pin
from services.ConsoleLogger import LogLevel, get_console_logger
from services.HardwareConfigService import HardwareConfigService
from services.Probing import ProbeError, probe_points

logger = logging.getLogger("backend.services.ZTiltService")

#: Must match ``ZTiltHalMapper.RAMP_MM_PER_S`` (the ramp in HAL).
RAMP_MM_PER_S = 2.0
#: A round whose spread grew past ``previous * this + tolerance`` stops.
GROWING_FACTOR = 1.5
#: The line that runs it from a macro or the homing routine.
COMMAND = "Z_TILT_ADJUST"


class ZTiltError(RuntimeError):
    """Why a Z tilt adjust stopped."""


class ZTiltService:
    def __init__(self, config: Optional[HardwareConfigService] = None) -> None:
        self._config = config or HardwareConfigService()
        self._pins: List[ReadWriteDynamicHalPin[float]] = []
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.last_result: Dict[str, Any] = {}

    # -- configuration ---------------------------------------------------- #

    def settings(self) -> Optional[Dict[str, Any]]:
        value = self._config.load_payload().get("z_tilt")
        return value if isinstance(value, dict) and value.get("joints") else None

    def preload_hal_pins(self) -> None:
        """One target pin per Z motor (``webgui.ztilt-<k>``). Call before
        ``HalPin.initialize_component()``."""
        if self._pins:
            return
        settings = self.settings()
        if settings is None:
            return
        self._pins = [
            ReadWriteDynamicHalPin[float](f"ztilt-{k}", HalDataType.FLOAT, f"Z tilt: motor {k} offset (mm)")
            for k in range(len(settings["joints"]))
        ]

    def offsets(self) -> List[float]:
        """The target offset per motor (mm), 0 while unset."""
        return [float(pin.get_value() or 0.0) for pin in self._pins]

    # -- running ---------------------------------------------------------- #

    def is_running(self) -> bool:
        worker = self._worker
        return worker is not None and worker.is_alive()

    def join(self, timeout: Optional[float] = None) -> None:
        worker = self._worker
        if worker is not None:
            worker.join(timeout)

    def start(self, busy: bool = False) -> None:
        """Check and start on a worker thread (the endpoint); returns at once."""
        settings = self._require_settings()
        stat = get_stat_channel()
        self._check_machine(stat, settings)
        if busy:
            raise ConflictError("A macro or the homing routine is running.")
        with self._lock:
            if self.is_running():
                raise ConflictError("Z tilt adjust is already running.")
            self._worker = threading.Thread(target=self._run_worker, name="z-tilt", daemon=True)
            self._worker.start()

    def _run_worker(self) -> None:
        console = get_console_logger()
        try:
            self.run(get_stat_channel())
        except ZTiltError as exc:
            console.log_event(f"Z tilt adjust aborted: {exc}", level=LogLevel.ERROR, source="CMD")
        except Exception as exc:  # noqa: BLE001 - report, don't die silently
            logger.exception("Z tilt adjust crashed: %s", exc)
            console.log_event(f"Z tilt adjust aborted: {exc}", level=LogLevel.ERROR, source="CMD")

    def run(self, stat: Any) -> List[float]:
        """The whole adjust, on the calling thread (a worker). Returns the
        final offsets; raises :class:`ZTiltError` with the reason it stopped."""
        settings = self._require_settings()
        self._check_machine(stat, settings)
        console = get_console_logger()
        points = [(float(x), float(y)) for x, y in settings["points"]]
        pivots = [(float(x), float(y)) for x, y in settings["z_positions"]]
        retries = int(settings.get("retries") or 0)
        tolerance = float(settings.get("retry_tolerance") or 0.0)
        max_adjust = float(settings.get("max_adjust") or 5.0)
        previous: Optional[float] = None

        for attempt in range(1, retries + 2):
            heights = self._probe_all(stat, settings, points)
            spread = max(heights) - min(heights)
            self.last_result = {"round": attempt, "heights": heights, "spread": spread}
            console.log_event(
                f"Z tilt round {attempt}: probed {', '.join(f'{h:.4f}' for h in heights)} "
                f"(spread {spread:.4f} mm).",
                level=LogLevel.INFO, source="CMD",
            )
            if retries and spread <= tolerance:
                console.log_event(f"Z tilt adjust done: within {tolerance:g} mm.", level=LogLevel.INFO, source="CMD")
                return self.offsets()
            if previous is not None and spread > previous * GROWING_FACTOR + tolerance:
                raise ZTiltError(
                    f"the spread grew from {previous:.4f} to {spread:.4f} mm — do z_positions match "
                    "[stepper_z], [stepper_z1], ... in that order?"
                )
            if retries and attempt == retries + 1:
                raise ZTiltError(f"still {spread:.4f} mm apart after {retries} retries (tolerance {tolerance:g}).")
            adjust = motor_adjustments(points, heights, pivots)
            targets = [current + delta for current, delta in zip(self.offsets(), adjust)]
            if any(abs(t) > max_adjust for t in targets):
                raise ZTiltError(
                    f"a correction of {max(abs(t) for t in targets):.3f} mm is beyond max_adjust "
                    f"({max_adjust:g} mm) — check the probe and z_positions."
                )
            console.log_event(
                "Z tilt: motor offsets " + ", ".join(f"{t:+.4f}" for t in targets) + " mm.",
                level=LogLevel.INFO, source="CMD",
            )
            self._apply(targets)
            previous = spread
        console.log_event("Z tilt adjust done.", level=LogLevel.INFO, source="CMD")
        return self.offsets()

    # -- steps ------------------------------------------------------------ #

    def _require_settings(self) -> Dict[str, Any]:
        settings = self.settings()
        if settings is None:
            raise BadRequestError("This machine has no [z_tilt] section.")
        if len(self._pins) != len(settings["joints"]):
            raise BadRequestError("Z tilt pins are not set up — restart the machine backend after regenerating.")
        return settings

    def _check_machine(self, stat: Any, settings: Dict[str, Any]) -> None:
        if stat is None:
            raise BadRequestError("Cannot adjust Z tilt: LinuxCNC is not running.")
        stat.poll()
        if stat.estop:
            raise BadRequestError("Cannot adjust Z tilt while the machine is in E-STOP.")
        if stat.task_state != MachineState.ON.value:
            raise BadRequestError("Turn the machine on before adjusting Z tilt.")
        homed = list(getattr(stat, "homed", ()) or ())
        needed = set(int(j) for j in settings["joints"])
        for axis in self._config.get_axes():
            if str(axis.get("id", "")).lower() in ("x", "y"):
                needed.update(int(j) for j in axis.get("joint_numbers") or [])
        missing = sorted(j for j in needed if not (j < len(homed) and homed[j]))
        if missing:
            raise BadRequestError(f"Home X, Y and Z first (joint(s) {', '.join(map(str, missing))} not homed).")

    def _probe_all(self, stat: Any, settings: Dict[str, Any], points: List[tuple[float, float]]) -> List[float]:
        try:
            return probe_points(
                stat, points,
                safe_z=float(settings.get("horizontal_move_z") or 5.0),
                travel_mm_s=float(settings.get("speed") or 50.0),
                probe_mm_s=float(settings.get("probe_speed") or 5.0),
                bottom=float(settings.get("probe_min_z") or 0.0),
            )
        except ProbeError as exc:
            raise ZTiltError(str(exc)) from exc

    def _apply(self, targets: List[float]) -> None:
        """Write the targets and wait until the ramps reached them."""
        current = self.offsets()
        for pin, target in zip(self._pins, targets):
            pin.set_value(float(target))
        travel = max((abs(t - c) for t, c in zip(targets, current)), default=0.0)
        deadline = time.monotonic() + travel / RAMP_MM_PER_S + 2.0
        while time.monotonic() < deadline:
            applied = [read_hal_pin(f"ztilt-ramp-{k}.out") for k in range(len(targets))]
            if all(a is not None and abs(float(a) - t) < 1e-4 for a, t in zip(applied, targets)):
                return
            if any(a is None for a in applied):
                # No HAL read-back (mock): the ramp's own time is enough.
                time.sleep(max(0.0, travel / RAMP_MM_PER_S))
                return
            time.sleep(0.05)
        raise ZTiltError("the motor offsets did not reach their targets in time.")


_SERVICE: Optional[ZTiltService] = None


def get_z_tilt_service() -> ZTiltService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = ZTiltService()
    return _SERVICE


__all__ = ["COMMAND", "ZTiltError", "ZTiltService", "get_z_tilt_service"]
