"""Request / response models of the system update (``/api/v1/system/update``)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

UpdateState = Literal["idle", "running", "done", "failed"]
#: commit — newest commit of the branch, frontend built on the board (testing).
#: release — a GitHub release with the frontend CI prebuilt (1 GB boards like the CB1).
UpdateMode = Literal["commit", "release"]


class SystemUpdateRequest(BaseModel):
    """Body of ``POST /system/update`` (optional — defaults to a commit update)."""

    mode: UpdateMode = Field(default="commit", description="commit: build the newest commit on the board; release: install the latest prebuilt release")


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
    mode: Optional[UpdateMode] = Field(default=None, description="commit | release; null for runs from before the modes existed")
    phase: str = Field(default="", description="Current / last step (pull, dependencies, rebuilding UI, ...)")
    message: str = Field(default="", description="Human-readable outcome")
    started_at: Optional[str] = Field(default=None, description="ISO-8601 start time")
    updated_at: Optional[str] = Field(default=None, description="ISO-8601 time of the last status write")
    finished_at: Optional[str] = Field(default=None, description="ISO-8601 end time (done / failed)")
    commit_before: Optional[str] = Field(default=None, description="Version before the update (git describe: release tag or short commit)")
    commit_after: Optional[str] = Field(default=None, description="Version after a successful update (git describe)")
    log_tail: str = Field(default="", description="Last lines of update.log (failed runs only)")


__all__ = ["SystemUpdateRequest", "SystemUpdateResponse", "UpdateMode", "UpdateState", "UpdateStatusResponse"]
