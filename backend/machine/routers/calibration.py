"""``/api/v1/calibration`` — the Calibration tab: every calibration of the
machine with its last result and reminder; start one, set / clear a
reminder, clear its saved values (``CalibrationService``)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from services.CalibrationService import get_calibration_service

router = APIRouter(prefix="/api/v1/calibration", tags=["calibration"])


class CalibrationParam(BaseModel):
    name: str
    default: float
    unit: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None


class CalibrationItem(BaseModel):
    id: str = Field(..., description="bed_mesh, z_tilt, probe_accuracy, probe_z_offset, pid_<heater>, input_shaper")
    kind: str = Field(..., description="The card type (instructions, benefit): the id without the heater.")
    label: str = Field("", description="The heater of a pid card.")
    available: bool
    reason: str = Field("", description="Why the machine cannot run it.")
    running: bool
    last_tested: Optional[str] = Field(None, description="ISO time of the last successful run.")
    result: Optional[str] = Field(None, description="Its result, one line.")
    remind_at: Optional[str] = Field(None, description="Reminder date (YYYY-MM-DD), once.")
    due: bool = Field(False, description="The reminder date is today or past.")
    params: List[CalibrationParam] = Field(default_factory=list)
    values: Dict[str, Any] = Field(default_factory=dict, description="The values in use (calibrated or the profile's).")


class CalibrationList(BaseModel):
    items: List[CalibrationItem]
    due: int = Field(0, description="Reminders due (the tab's badge).")


class StartRequest(BaseModel):
    params: Dict[str, float] = Field(default_factory=dict)


class StartResponse(BaseModel):
    command: str


class ReminderRequest(BaseModel):
    remind_at: Optional[str] = Field(None, description="YYYY-MM-DD; null removes the reminder.")


def _list() -> CalibrationList:
    return CalibrationList(**get_calibration_service().listing())


@router.get("", response_model=CalibrationList, operation_id="getCalibrations",
            summary="The machine's calibrations, results and reminders")
def get_calibrations() -> CalibrationList:
    return _list()


@router.post("/{calibration_id}/start", response_model=StartResponse, operation_id="startCalibration",
             summary="Start a calibration (its console command)",
             responses={400: {"description": "Not available / bad parameter."}, 404: {"description": "Unknown."},
                        409: {"description": "Already running."}})
def start_calibration(calibration_id: str, payload: StartRequest) -> StartResponse:
    return StartResponse(command=get_calibration_service().start(calibration_id, payload.params))


@router.put("/{calibration_id}/reminder", response_model=CalibrationList, operation_id="setCalibrationReminder",
            summary="Set or remove a calibration's reminder", responses={400: {"description": "Not a date."}})
def set_reminder(calibration_id: str, payload: ReminderRequest) -> CalibrationList:
    get_calibration_service().set_reminder(calibration_id, payload.remind_at)
    return _list()


@router.delete("/{calibration_id}/values", response_model=CalibrationList, operation_id="clearCalibration",
               summary="Back to the profile's values (calibration.ini entries removed)",
               responses={400: {"description": "It saves no values."}, 404: {"description": "Unknown."}})
def clear_values(calibration_id: str) -> CalibrationList:
    get_calibration_service().clear(calibration_id)
    return _list()
