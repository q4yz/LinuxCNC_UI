"""``G29`` — level the machine (`.agent/component/bed_mesh.md` § 5,
`z_tilt.md`): ``Z_TILT_ADJUST`` when it has ``[z_tilt]``, then
``BED_MESH_CALIBRATE`` when it has ``[bed_mesh]``. A print's start
G-code ``G29`` (``PrintStartService``) and MDI ``G29`` run it.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from exceptions import BaseAPIException, ConflictError
from hardware import get_stat_channel
from services.ConsoleLogger import LogLevel, get_console_logger

logger = logging.getLogger("backend.services.LevelingService")

_worker: Optional[threading.Thread] = None
_lock = threading.Lock()


def level(stat: Any) -> Optional[str]:
    """Run whatever the machine has, on the calling worker; the reason it
    stopped, or ``None`` (also when there is nothing to do — logged)."""
    from services.BedMeshProbeService import BedMeshError, get_bed_mesh_probe_service
    from services.ZTiltService import ZTiltError, get_z_tilt_service

    console = get_console_logger()
    z_tilt, mesh = get_z_tilt_service(), get_bed_mesh_probe_service()
    if z_tilt.settings() is None and mesh.settings() is None:
        console.log_event("G29 skipped: this machine has no [z_tilt] and no [bed_mesh].",
                          level=LogLevel.WARNING, source="CMD")
        return None
    try:
        if z_tilt.settings() is not None:
            console.log_event("G29: Z_TILT_ADJUST.", level=LogLevel.INFO, source="CMD")
            z_tilt.run(stat)
        if mesh.settings() is not None:
            console.log_event("G29: BED_MESH_CALIBRATE.", level=LogLevel.INFO, source="CMD")
            mesh.run(stat)
    except (ZTiltError, BedMeshError) as exc:
        return str(exc)
    except BaseAPIException as exc:
        return str(exc.detail)
    return None


def is_running() -> bool:
    return _worker is not None and _worker.is_alive()


def start(busy: bool = False) -> None:
    """MDI ``G29``: :func:`level` on a worker thread."""
    global _worker
    if busy:
        raise ConflictError("A macro, the homing routine or probing is running.")
    with _lock:
        if is_running():
            raise ConflictError("Leveling is already running.")

        def run() -> None:
            reason = level(get_stat_channel())
            if reason is not None:
                get_console_logger().log_event(f"G29 aborted: {reason}", level=LogLevel.ERROR, source="CMD")

        _worker = threading.Thread(target=run, name="leveling", daemon=True)
        _worker.start()


__all__ = ["is_running", "level", "start"]
