import time
from typing import Dict, Union

from core.field_masking import ResponseTier
from mapper.BaseThreadSnapshotMapper import BaseThreadSnapshotMapper
from models.BaseThreadStateResponse import BaseThreadSnapshotResponse
from modules.axis.mapper.axis_mapper import AxisMapper
from modules.axis.models.axis_model import AxisStateResponse
from modules.axis.services.service import get_axis_service
from modules.program.service import ProgramProgressResponse, get_program_lifecycle_service
from modules.temperature.factory.TemperatureResponseFactory import TemperatureResponseFactory
from modules.temperature.models.TemperatureResponse import TemperatureStateResponse
from modules.temperature.services.TemperatureService import get_temperature_service
from modules.tools.factory.ToolResponseFactory import ToolResponseFactory, ToolStateResponseModel
from modules.tools.models.HeaterModels import HeaterStateResponse
from modules.tools.services.ToolsService import get_tools_service
from tests.non_repeating_logger import NonRepeatingLogger

logger = NonRepeatingLogger("backend.services.base_thread")


class BaseThreadSnapshotService:
    """Service responsible for aggregating and building the base-thread snapshots."""

    def __init__(self):
        self.tool_service = get_tools_service()
        self.axes_service = get_axis_service()
        self.temperature_service = get_temperature_service()
        self.program_service = get_program_lifecycle_service()

    def _read_progress(self) -> ProgramProgressResponse:
        progress = self.program_service.progress_program()
        logger.debug(
            "base_thread.snapshot: progress built file=%r current=%d total=%d interp=%d",
            progress.file,
            progress.current_line,
            progress.total_lines,
            progress.interp_state,
        )
        return progress

    def _tools_snapshot(self, mode: ResponseTier) -> Dict[str, ToolStateResponseModel]:
        """Build the operator-facing tool list via the OOP factories."""
        logger.info("base_thread.snapshot: building tools overlay")
        out: Dict[str, ToolStateResponseModel] = {}

        states = self.tool_service.get_states()
        logger.debug("base_thread.snapshot: tools service returned %d state(s)", len(states))

        for state in states:
            # Pass the mode down to the factory!
            response_model: ToolStateResponseModel = ToolResponseFactory.create(state, mode)
            if response_model is not None:
                out[response_model.id] = response_model

        if not out:
            logger.warning(
                "base_thread.snapshot: tools overlay is empty — check hardware.json "
                "tools[] and the spindle pin subscriptions"
            )
        return out

    def _sensors_snapshot(self, mode: ResponseTier) -> Dict[str, Union[HeaterStateResponse, TemperatureStateResponse]]:
        """Build the sensors dictionary using the strongly typed response models."""
        logger.info("base_thread.snapshot: building sensors overlay")
        out: Dict[str, Union[HeaterStateResponse, TemperatureStateResponse]] = {}

        states = self.temperature_service.get_states()
        logger.debug("base_thread.snapshot: temperature service returned %d state(s)", len(states))

        for state in states:
            # Pass the mode down to the factory!
            response_model = TemperatureResponseFactory.create(state, mode)
            if response_model is not None:
                out[response_model.id] = response_model

        if not out:
            logger.warning(
                "base_thread.snapshot: sensors overlay is empty — check hardware.json "
                "temperature_sensors[] / tools[] heater declarations"
            )
        return out

    def _axis_state(self, mode: ResponseTier) -> Dict[str, AxisStateResponse]:
        out = {}
        for axis in self.axes_service.get_axis():
            # Pass the mode down to the mapper!
            # Note: Ensure AxisMapper.from_dto_to_response is updated to accept the mode arg
            response = AxisMapper.to_response(axis, mode)
            out[response.id] = response
        return out

    # --- MAIN ENGINE ---

    def get_snapshot(self, mode: ResponseTier = ResponseTier.ALL) -> BaseThreadSnapshotResponse:
        """Assembles the snapshot based on the requested mode."""
        started = time.monotonic()

        logger.info("base_thread.snapshot: assembling dashboard payload mode=%s", mode.value)

        # Program progress (current G-code line) has no static config, so only fetch it for BASE or ALL
        include_progress = (mode in {ResponseTier.BASE, ResponseTier.ALL})

        progress = self._read_progress() if include_progress else None

        # Tools, Sensors, and Axes all have both static (limits, max_rpm) and base (actual_rpm, pos) data.
        # We fetch them every time, but pass the `mode` down so the mappers can strip out the irrelevant fields.
        sensors = self._sensors_snapshot(mode)
        tools = self._tools_snapshot(mode)
        axis = self._axis_state(mode)

        elapsed_ms = (time.monotonic() - started) * 1000.0
        logger.info(
            "base_thread.snapshot: assembled sensors=%d tools=%d in %.1fms",
            len(sensors) if sensors else 0,
            len(tools) if tools else 0,
            elapsed_ms,
        )

        return BaseThreadSnapshotMapper.to_response(
            progress=progress,
            sensors=sensors,
            tools=tools,
            axis=axis,
        )

    # --- WRAPPERS ---

    def get_base_response(self) -> BaseThreadSnapshotResponse:
        """Returns ONLY the dynamic 1Hz data."""
        return self.get_snapshot(ResponseTier.BASE)

    def get_static_response(self) -> BaseThreadSnapshotResponse:
        """Returns ONLY the static machine configuration."""
        return self.get_snapshot(ResponseTier.STATIC)


_SERVICE_INSTANCE = None


def get_base_thread_service() -> BaseThreadSnapshotService:
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = BaseThreadSnapshotService()
    return _SERVICE_INSTANCE