"""Legacy ``/api/v1/config`` HTTP surface.

Thin wrapper around :class:`ConfigFileService` that keeps the
endpoint contracts (``GET /api/v1/config``, ``GET /api/v1/config/{filename}``,
``POST /api/v1/config/{filename}``) byte-for-byte identical to the
pre-refactor version. The router no longer imports ``os``,
``pathlib``, ``MachineConfig``, or ``HalCompiler`` — every disk
operation is delegated to the service layer.

The legacy ``/compile/generate`` and ``/compile/deploy`` endpoints
are dropped in this refactor (issue #49): they were superseded by
the machineconfig module's ``/compile`` and ``/deploy`` routes and
are no longer wired into the frontend.
"""

import logging
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services import ConfigFileService, get_config_service

logger = logging.getLogger("backend.routers.config")
router = APIRouter(prefix="/api/v1/config", tags=["Configuration"])


class ConfigContent(BaseModel):
    """Pydantic model for the body of POST /config/{filename}."""

    content: str = Field(..., description="Raw text content to overwrite the profile file with")


class ConfigProfileInfo(BaseModel):
    """Metadata describing a single editable profile file."""

    filename: str = Field(..., description="Filename (basename, no path)")
    size_bytes: int = Field(..., description="File size in bytes")


class ConfigFileContent(BaseModel):
    """Response model for GET /config/{filename}."""

    filename: str = Field(..., description="Sanitized filename that was read")
    content: str = Field(..., description="Raw text content of the profile file")


class StatusMessageResponse(BaseModel):
    """Generic response model containing a status string and an informational message."""

    status: str = Field(..., description="Outcome summary (e.g., 'ok')")
    message: str = Field(..., description="Human-readable confirmation message")


def _sanitize_profile_filename(filename: str) -> str:
    cleaned = filename.strip().replace("\\", "/").split("/")[-1]
    if not cleaned or cleaned in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid profile filename.")
    if not cleaned.lower().endswith(".cfg"):
        cleaned = f"{cleaned}.cfg"
    return cleaned


@router.get(
    "",
    summary="List Config Profiles",
    description="Returns all profile configuration files from machine_config/profiles.",
    operation_id="listConfigs",
    response_model=List[ConfigProfileInfo],
)
def list_configs() -> List[ConfigProfileInfo]:
    """List editable source profiles from the profiles/ root only."""
    try:
        service: ConfigFileService = get_config_service()
        # Legacy contract: only top-level .cfg files. Use the dedicated
        # filter so we surface the same files the old ``os.listdir``
        # call did, regardless of how deep any sub-folders go.
        service.filename_filter = ConfigFileService.cfg_filter
        entries = [e for e in service.list_files() if e.parent is None]
        return [
            ConfigProfileInfo(filename=entry.name, size_bytes=entry.size_bytes)
            for entry in entries
        ]
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        logger.error("Failed to list config profiles: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list config profiles.")


@router.get(
    "/{filename}",
    summary="Read Profile File",
    description="Returns raw text content of a profile file from machine_config/profiles.",
    operation_id="readConfig",
    response_model=ConfigFileContent,
)
def read_config(filename: str) -> ConfigFileContent:
    """Read a profile from the profiles/ root only."""
    safe_name = _sanitize_profile_filename(filename)
    service: ConfigFileService = get_config_service()
    try:
        content = service.read_file(safe_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Config profile not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        logger.error("Failed to read config profile %s: %s", safe_name, exc)
        raise HTTPException(status_code=500, detail="Failed to read config profile.") from exc
    return ConfigFileContent(filename=safe_name, content=content)


@router.post(
    "/{filename}",
    summary="Save Profile File",
    description="Overwrites a profile file in machine_config/profiles.",
    operation_id="saveConfig",
    response_model=StatusMessageResponse,
)
def save_config(filename: str, payload: ConfigContent) -> StatusMessageResponse:
    """Save profile content to the profiles/ root only."""
    safe_name = _sanitize_profile_filename(filename)
    service: ConfigFileService = get_config_service()
    try:
        service.write_file(safe_name, payload.content, overwrite=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Config profile not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        logger.error("Failed to save config profile %s: %s", safe_name, exc)
        raise HTTPException(status_code=500, detail="Failed to save config profile.") from exc
    return StatusMessageResponse(status="ok", message=f"Saved {safe_name}")


# ``compile_generate`` and ``compile_deploy`` were dropped as part
# of the issue #49 refactor — the machineconfig module's
# ``/compile`` and ``/deploy`` endpoints supersede them and the
# frontend has migrated. We keep no backward-compatibility shims
# because the surface is documented as gone.
