"""Request / response models of the machineconfig router (profiles, machines, M-codes)."""
from typing import List, Optional
from pydantic import BaseModel, Field

from models.FileModels import FileEntryResponse


class StatusMessage(BaseModel):
    """Generic status + message response."""

    status: str = Field(..., description="Outcome summary (e.g. 'ok')")
    message: str = Field(..., description="Human-readable confirmation")



class DirectoryListing(BaseModel):
    """Flat listing of every file/folder under a root."""

    root: str = Field(..., description="'profiles' | 'staged' | 'active'")
    entries: List[FileEntryResponse] = Field(default_factory=list)


class ProfileContent(BaseModel):
    """Payload returned by ``GET /profiles/content?path=<rel>``."""

    path: str = Field(..., description="Forward-slash path relative to profiles/")
    content: str = Field(..., description="Raw text content of the file")


class ProfileWriteRequest(BaseModel):
    """Body of ``PUT /profiles/content?path=<rel>``."""

    content: str = Field(..., description="Raw text to overwrite the file with")



class MCodeListResponse(BaseModel):
    """Response body of ``GET /m-codes/list``."""

    mcodes: List[FileEntryResponse] = Field(
        default_factory=list,
        description="Sorted list of M-codes currently on disk.",
    )


class MCodeContentResponse(BaseModel):
    """Response body of ``GET /m-codes/content?path=<name>``."""

    path: str = Field(..., description="M-code token")
    content: str = Field(..., description="Raw text content of the file")


class MCodeWriteRequest(BaseModel):
    """Body of ``PUT /m-codes/content?path=<name>``."""

    content: str = Field(..., description="Raw text to overwrite the M-code with")


class MCodeStatusMessage(BaseModel):
    """Response body for ``PUT`` / ``DELETE`` on M-codes."""

    status: str = Field(default="ok", description="Status indicator.")
    message: str = Field(..., description="Human-readable confirmation.")


class CreateEntryRequest(BaseModel):
    """Body of ``POST /profiles/folder`` and ``POST /profiles/file``."""

    path: str = Field(
        ...,
        description="Forward-slash path relative to profiles/, including the new name",
    )


class RenameRequest(BaseModel):
    """Body of ``PUT /profiles/rename``."""

    source: str = Field(..., description="Existing relative path")
    destination: str = Field(..., description="New relative path")


class GenerateRequest(BaseModel):
    """Body of ``POST /machines/generate``."""

    profile_path: str = Field(
        ..., description="Forward-slash path relative to profiles/"
    )
    target_folder: str = Field(
        default="",
        description=(
            "Optional folder under machines/ to nest the machine folder "
            "in (supports operator grouping). Empty = machines/ root."
        ),
    )
    confirm_override: bool = Field(
        default=False,
        description=(
            "Set true to replace an existing machine folder. When false "
            "and the machine already exists the endpoint answers 409."
        ),
    )


class MachineFile(BaseModel):
    """One file written by ``POST /machines/generate``."""

    name: str = Field(..., description="Basename of the generated file")
    path: str = Field(
        ..., description="Forward-slash path relative to machines/"
    )
    size_bytes: int = Field(default=0, description="File size in bytes")


class GenerateResponse(BaseModel):
    """Response of ``POST /machines/generate``."""

    status: str = Field(..., description="Outcome summary (e.g. 'ok')")
    machine: str = Field(..., description="Machine name (the profile file stem)")
    target_folder: str = Field(
        default="", description="Folder under machines/ the machine lives in"
    )
    files: List[MachineFile] = Field(
        default_factory=list, description="Generated template files"
    )
