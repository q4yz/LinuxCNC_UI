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


from services import get_machine_control_service, ProgramProgressResponse
from services.machine_service import collect_sensors, collect_tools

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


def _read_progress() -> ProgramProgressResponse:
    return get_machine_control_service().progress_program()



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

    progress = _read_progress()
    sensors = collect_sensors()
    tools = collect_tools()





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
