"""Request / response models of the system update (``/api/v1/system/update``)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

UpdateState = Literal["idle", "running", "done", "failed"]


class SystemUpdateResponse(BaseModel):
    """Response of ``POST /system/update``."""

    status: str = Field(..., description="Outcome summary describing the update state")
    run_id: str = Field(..., description="Id of this update run — poll /update/status for it")


class UpdateStatusResponse(BaseModel):
    """Progress of the last system update (``GET /system/update/status``).

    Written by ``scripts/update.sh``. ``done`` is only written after the
    restarted services answered, so the UI may reload on it.
    """

    run_id: Optional[str] = Field(default=None, description="Id of the run; null when no update ever ran")
    state: UpdateState = Field(..., description="idle | running | done | failed")
    phase: str = Field(default="", description="Current / last step (pull, dependencies, rebuilding UI, ...)")
    message: str = Field(default="", description="Human-readable outcome")
    started_at: Optional[str] = Field(default=None, description="ISO-8601 start time")
    updated_at: Optional[str] = Field(default=None, description="ISO-8601 time of the last status write")
    finished_at: Optional[str] = Field(default=None, description="ISO-8601 end time (done / failed)")
    commit_before: Optional[str] = Field(default=None, description="Short commit before the update")
    commit_after: Optional[str] = Field(default=None, description="Short commit after a successful update")
    log_tail: str = Field(default="", description="Last lines of update.log (failed runs only)")


__all__ = ["SystemUpdateResponse", "UpdateState", "UpdateStatusResponse"]
