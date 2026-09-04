"""Mapper for the base-thread snapshot response.

Builds a :class:`models.BaseThreadStateResponse.BaseThreadSnapshotResponse`
from the already-populated sub-snapshot dicts produced by the
``_read_progress`` / ``_sensors_snapshot`` / ``_tools_snapshot`` /
``_axis_state`` helpers in :mod:`routers.base_thread`.

The router owns the decision of *which* sub-snapshots to compute
(controlled by ``?mode=``); this mapper only assembles the
:class:`BaseThreadSnapshotResponse` and stamps the snapshot's
``timestamp``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Union

from models.BaseThreadStateResponse import BaseThreadSnapshotResponse
from models.axis_model import AxisStateResponse
from services.ProgramService import ProgramProgressResponse
from models.temperature_response import TemperatureStateResponse
from factories.tools.ToolResponseFactory import ToolStateResponseModel
from models.tools.HeaterModels import HeaterStateResponse


def _utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


class BaseThreadSnapshotMapper:
    """Assembles the per-request base-thread snapshot payload."""

    @classmethod
    def to_response(
        cls,
        *,
        progress: Optional[ProgramProgressResponse] = None,
        sensors: Optional[Dict[str, Union[HeaterStateResponse, TemperatureStateResponse]]] = None,
        tools: Optional[Dict[str, ToolStateResponseModel]] = None,
        axis: Optional[Dict[str, AxisStateResponse]] = None,
    ) -> BaseThreadSnapshotResponse:
        """Return a snapshot whose ``None`` sub-snapshots will be
        stripped by the route's ``response_model_exclude_none=True``.
        """
        return BaseThreadSnapshotResponse(
            progress=progress,
            sensors=sensors,
            tools=tools,
            axis=axis,
            timestamp=_utc_timestamp(),
        )
