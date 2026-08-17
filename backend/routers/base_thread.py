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

Concurrency: the snapshot reads from ``linuxcnc.stat`` exactly
once per request, so it cannot race against the WebSocket
telemetry loop beyond what NML already coordinates.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Union

from fastapi import APIRouter
from pydantic import BaseModel, Field


from modules.program.service import (
    ProgramProgressResponse,
    get_program_lifecycle_service,
)

from modules.temperature.factory.temperature_response_factory import TemperatureResponseFactory

from modules.temperature.models.temperature_models import TemperatureStateResponse
from modules.temperature.services.temperature_service import get_temperature_service
from modules.tools.factory.tool_response_factory import ToolResponseFactory, ToolStateResponseModel

from modules.tools.models.heater_models import HeaterStateResponse
from modules.tools.services.tool_service import get_tools_service
from tests.non_repeating_logger import NonRepeatingLogger

logger = NonRepeatingLogger("backend.routers.base_thread")

router = APIRouter(prefix="/api/v1/base-thread", tags=["Base Thread"])

tool_service = get_tools_service()


class BaseThreadSnapshotResponse(BaseModel):
    """Flat snapshot of every slow stream the dashboard polls at 1 Hz."""

    progress: ProgramProgressResponse = Field(...,
        description=(
            "Active program progress: ``current_line`` / ``motion_line`` "
            "from ``linuxcnc.stat`` plus the cached ``total_lines``."
        ),
    )
    sensors: Dict[str, Union[HeaterStateResponse, TemperatureStateResponse]] = Field(
        default_factory=dict,
        description=(
            "Temperature sensors keyed by ID. Tool heaters include target/min/max, "
            "while standalone sensors only report actual temperatures."
        ),
    )
    tools: List[ToolStateResponseModel] = Field(
        default_factory=list,
        description=(
            "Operator-facing tool list with runtime state overlaid."
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
    progress = get_program_lifecycle_service().progress_program()
    logger.debug(
        "base_thread.snapshot: progress built file=%r current=%d total=%d interp=%d",
        progress.file,
        progress.current_line,
        progress.total_lines,
        progress.interp_state,
    )
    return progress

# ---------------------------------------------------------------------- #
# Tools overlay                                                          #
# ---------------------------------------------------------------------- #

def _tools_snapshot() -> List[ToolStateResponseModel]:
    """Build the operator-facing tool list via the OOP factories."""
    logger.info("base_thread.snapshot: building tools overlay")
    out: List[ToolStateResponseModel] = []

    states = tool_service.get_states()
    logger.debug(
        "base_thread.snapshot: tools service returned %d state(s)", len(states)
    )

    for state in states:
        response_model = ToolResponseFactory.create(state)
        if response_model is not None:
            out.append(response_model)

    if not out:
        logger.warning(
            "base_thread.snapshot: tools overlay is empty — check hardware.json "
            "tools[] and the spindle pin subscriptions"
        )
    else:
        logger.debug(
            "base_thread.snapshot: tools overlay built ids=%s",
            [getattr(t, "id", "?") for t in out],
        )
    return out


def _sensors_snapshot() -> Dict[str, Union[HeaterStateResponse, TemperatureStateResponse]]:
    """Build the sensors dictionary using the strongly typed response models."""
    logger.info("base_thread.snapshot: building sensors overlay")
    out: Dict[str, Union[HeaterStateResponse, TemperatureStateResponse]] = {}

    states = get_temperature_service().get_states()
    logger.debug(
        "base_thread.snapshot: temperature service returned %d state(s)", len(states)
    )

    for state in states:
        response_model = TemperatureResponseFactory.create(state)
        if response_model is not None:
            out[response_model.tool_id] = response_model

    if not out:
        logger.warning(
            "base_thread.snapshot: sensors overlay is empty — check hardware.json "
            "temperature_sensors[] / tools[] heater declarations"
        )
    else:
        logger.debug(
            "base_thread.snapshot: sensors overlay built ids=%s", sorted(out.keys())
        )
    return out

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
    """Assemble the 1 Hz dashboard snapshot in one shot."""
    started = time.monotonic()
    logger.info("base_thread.snapshot: assembling dashboard payload")

    progress = _read_progress()
    sensors = _sensors_snapshot()
    tools = _tools_snapshot()

    timestamp = (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )

    elapsed_ms = (time.monotonic() - started) * 1000.0
    logger.info(
        "base_thread.snapshot: assembled sensors=%d tools=%d in %.1fms",
        len(sensors),
        len(tools),
        elapsed_ms,
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
