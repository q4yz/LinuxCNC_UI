"""Base-thread snapshot endpoint.

LinuxCNC's runtime uses two parallel threads:

* a fast **servo thread** that handles time-critical work
  (position controllers, trajectory planner);
* a slower **base thread** that handles bookkeeping (UI updates,
  status reporting).

The web UI mirrors that split:

* the 10 Hz WebSocket ``/ws/telemetry`` stream is the "servo
  thread" — it carries estop, task_state, position, errors, and
  anything the DRO / status panels need on every frame;
* this endpoint is the "base thread" — one round-trip per second
  collects every slow stream the dashboard cares about
  (program progress, temperature sensors, tool list) in a single
  payload so the browser only needs **one** HTTP request per second
  regardless of how many panels are mounted.

The endpoint is intentionally flat: every slow stream lands as a
top-level field on the response so adding a new stream in the
future only touches the Pydantic model, the generated TS type, and
the snapshot handler below. No version field — unknown top-level
keys are ignored by the frontend.

Concurrency: the snapshot reads from ``linuxcnc.stat`` exactly
once per request, so it cannot race against the WebSocket
telemetry loop beyond what NML already coordinates.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hardware import get_machine_stat, linuxcnc
from modules.program.router import ProgramProgressResponse
from modules.temperature.router import _collect_sensors
from modules.tools.router import _collect_tools
from services import lookup_line_count

logger = logging.getLogger("backend.routers.base_thread")

router = APIRouter(prefix="/api/v1/base-thread", tags=["Base Thread"])


class BaseThreadSnapshotResponse(BaseModel):
    """Flat snapshot of every slow stream the dashboard polls at 1 Hz.

    New streams are added by introducing a new top-level field here
    AND in the generated TypeScript model. The frontend
    ``baseThread`` store consumes the response via ``storeToRefs``
    and exposes each field as its own reactive ref, so adding a
    stream does not require touching any consumer module.
    """

    progress: ProgramProgressResponse = Field(
        ...,
        description=(
            "Active program progress: ``current_line`` / ``motion_line`` "
            "from ``linuxcnc.stat`` plus the cached ``total_lines``."
        ),
    )
    sensors: Dict[str, Dict[str, float]] = Field(
        default_factory=dict,
        description=(
            "Temperature sensors keyed by name; each entry has "
            "``actual`` / ``target``."
        ),
    )
    tools: List[dict] = Field(
        default_factory=list,
        description=(
            "Operator-facing tool list with runtime state overlaid "
            "(``actual`` / ``target`` for heating tools, "
            "``actual_rpm`` for digital spindles)."
        ),
    )
    timestamp: str = Field(
        ...,
        description=(
            "ISO-8601 timestamp the snapshot was assembled (UTC). "
            "Lets the frontend detect a stalled / paused poll."
        ),
    )


def _empty_progress() -> ProgramProgressResponse:
    """Safe zeroed progress snapshot for the offline / unloaded case.

    Used when the NML stat channel is offline so the snapshot
    endpoint never raises — the dashboard's empty-state UI handles
    the no-data case cleanly.
    """
    return ProgramProgressResponse(
        current_line=0,
        motion_line=0,
        total_lines=0,
        file="",
        interp_state=int(getattr(linuxcnc, "INTERP_IDLE", 1)),
    )


def _read_progress(stat) -> ProgramProgressResponse:
    """Read the current program progress from the NML stat channel.

    The function polls the channel first so a fresh connection that
    hasn't yet broadcast a progress frame still returns valid
    numbers. ``current_line`` / ``motion_line`` are read with
    ``getattr`` defaults because older mock revisions did not
    populate ``motion_line`` and a fresh connection can briefly
    return ``None`` for either field before the first poll lands.

    The ``total_lines`` field comes from the line-count cache
    populated at ``POST /load`` time (real LinuxCNC never reports
    a total; the cache is the authoritative source). The cache is
    cleared at ``POST /unload`` so a stale total can never leak
    across runs.
    """
    poll = getattr(stat, "poll", None)
    if callable(poll):
        poll()
    file_path = str(getattr(stat, "file", "") or "")
    current_line = int(getattr(stat, "current_line", 0) or 0)
    motion_line = int(getattr(stat, "motion_line", 0) or 0)
    interp_state = int(
        getattr(stat, "interp_state", getattr(linuxcnc, "INTERP_IDLE", 1))
        or getattr(linuxcnc, "INTERP_IDLE", 1)
    )
    return ProgramProgressResponse(
        current_line=max(0, current_line),
        motion_line=max(0, motion_line),
        total_lines=max(0, lookup_line_count(file_path)),
        file=file_path,
        interp_state=interp_state,
    )


@router.get(
    "/snapshot",
    response_model=BaseThreadSnapshotResponse,
    summary="Get Base-Thread Snapshot",
    description=(
        "Return the union of every slow stream the dashboard polls "
        "at 1 Hz: program progress (current line / total), "
        "temperature sensors, and the operator-facing tool list. "
        "One round-trip per second keeps the browser off the slow "
        "REST endpoints entirely; the 10 Hz WebSocket "
        "``/ws/telemetry`` continues to carry the time-critical "
        "fields (state, position, errors)."
    ),
    operation_id="getBaseThreadSnapshot",
)
def get_base_thread_snapshot() -> BaseThreadSnapshotResponse:
    """Assemble the 1 Hz dashboard snapshot in one shot.

    The handler never raises — a missing NML stat channel returns
    the safe-zeroed payload so the operator's UI shows "LinuxCNC
    not running" rather than a 5xx. Every sub-collector is
    None-safe for the same reason.
    """
    stat = get_machine_stat()
    if stat is None:
        progress = _empty_progress()
        sensors: Dict[str, Dict[str, float]] = {}
        tools: List[dict] = []
    else:
        progress = _read_progress(stat)
        sensors = _collect_sensors()
        tools = _collect_tools()

    timestamp = (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )

    return BaseThreadSnapshotResponse(
        progress=progress,
        sensors=sensors,
        tools=tools,
        timestamp=timestamp,
    )


__all__ = [
    "router",
    "BaseThreadSnapshotResponse",
    "get_base_thread_snapshot",
]
