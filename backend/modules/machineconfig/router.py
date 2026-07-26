"""HTTP router for the machineconfig module.

Endpoint groups (mounted by the registry under
``/api/v1/modules/machineconfig``):

* **Profiles CRUD** — full hierarchical read/write of
  ``machine_config/profiles`` (list, read, write, create folder,
  create file, delete, rename).
* **Compilers** — ``GET /compilers`` returns the registered compilers
  plus a marker probe (``has_marker``) per file under ``profiles``.
* **Compile** — ``POST /compile`` runs the selected compiler against
  a chosen profile and stages the artifacts into
  ``machine_config/ready_for_deploy``.
* **Staged / Active read-only** — ``GET /staged`` and
  ``GET /active`` plus per-file content endpoints. Operators can
  inspect the staged and active payloads but cannot edit them
  through this surface.
* **Deploy** — ``POST /deploy`` promotes the staged payload into
  ``machine_config/active``. Accepts ``confirm_flash`` to satisfy
  remote-controller (e.g. Remora) workflows.
* **Machine name** — ``GET /machine-name`` reads the current machine
  name out of the active INI so the Active dashboard can render the
  "currently running machine" header.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import filesystem
from .compilers import registry as compiler_registry

logger = logging.getLogger("backend.modules.machineconfig.router")

router = APIRouter(tags=["modules:machineconfig"])


# ---------------------------------------------------------------------- #
# Pydantic models                                                         #
# ---------------------------------------------------------------------- #


class StatusMessage(BaseModel):
    """Generic status + message response."""

    status: str = Field(..., description="Outcome summary (e.g. 'ok')")
    message: str = Field(..., description="Human-readable confirmation")


class DirectoryEntryModel(BaseModel):
    """Single node in a directory listing.

    Mirrors :class:`backend.modules.machineconfig.filesystem.DirectoryEntry`
    but in the Pydantic shape the frontend codegen can type-check.
    """

    name: str = Field(..., description="Basename of the entry")
    path: str = Field(
        ..., description="Forward-slash path relative to the root directory"
    )
    parent: Optional[str] = Field(
        default=None,
        description="Parent path relative to the root, or null at the top level",
    )
    kind: str = Field(..., description="'file' or 'folder'")
    size_bytes: int = Field(default=0, description="File size in bytes (0 for folders)")
    has_marker: bool = Field(
        default=False,
        description=(
            "True when the file contains the active compiler's source marker "
            "(e.g. '#Start'). Drives the inline 'Compile' button."
        ),
    )


class DirectoryListing(BaseModel):
    """Flat listing of every file/folder under a root."""

    root: str = Field(..., description="'profiles' | 'staged' | 'active'")
    entries: List[DirectoryEntryModel] = Field(default_factory=list)


class ProfileContent(BaseModel):
    """Payload returned by ``GET /profiles/content/{path}``."""

    path: str = Field(..., description="Forward-slash path relative to profiles/")
    content: str = Field(..., description="Raw text content of the file")


class ProfileWriteRequest(BaseModel):
    """Body of ``PUT /profiles/content/{path}``."""

    content: str = Field(..., description="Raw text to overwrite the file with")


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


class CompilerSummary(BaseModel):
    """Single compiler entry in the registry listing."""

    id: str = Field(..., description="Stable compiler id (kebab-case)")
    title: str = Field(..., description="Display title for the dropdown")
    source_marker: Optional[str] = Field(
        default=None,
        description="Marker substring this compiler looks for, or null",
    )


class CompilerListResponse(BaseModel):
    """Response of ``GET /compilers``."""

    compilers: List[CompilerSummary] = Field(default_factory=list)


class CompileRequest(BaseModel):
    """Body of ``POST /compile``."""

    profile_path: str = Field(
        ..., description="Forward-slash path relative to profiles/"
    )
    compiler_id: str = Field(..., description="Registered compiler id")


class StagedFile(BaseModel):
    """One file currently sitting in ``ready_for_deploy``."""

    name: str = Field(..., description="Basename of the staged file")
    size_bytes: int = Field(..., description="File size in bytes")


class CompileResponse(BaseModel):
    """Response of ``POST /compile``."""

    status: str = Field(..., description="Outcome summary (e.g. 'ok')")
    compiler: str = Field(..., description="Compiler id that produced the staged payload")
    profile: str = Field(..., description="Source profile path that was compiled")
    artifacts: List[str] = Field(default_factory=list, description="Filenames written under ready_for_deploy")
    staged: List[StagedFile] = Field(
        default_factory=list, description="Resulting listing of ready_for_deploy"
    )


class StagedContent(BaseModel):
    """Payload returned by ``GET /staged/content/{name}``."""

    name: str = Field(..., description="Filename inside ready_for_deploy")
    content: str = Field(..., description="Raw text content")
    read_only: bool = Field(
        default=True,
        description="Always true; staged files are write-protected after compile",
    )


class ActiveFile(BaseModel):
    """One file currently sitting in ``active``."""

    name: str = Field(..., description="Basename of the active file")
    size_bytes: int = Field(..., description="File size in bytes")


class ActiveListing(BaseModel):
    """Response of ``GET /active``."""

    machine_name: Optional[str] = Field(
        default=None, description="Machine name from the active INI's [EMC] section"
    )
    files: List[ActiveFile] = Field(default_factory=list)


class ActiveContent(BaseModel):
    """Payload returned by ``GET /active/content/{name}``."""

    name: str = Field(..., description="Filename inside active")
    content: str = Field(..., description="Raw text content")


class DeployRequest(BaseModel):
    """Body of ``POST /deploy``."""

    confirm_flash: bool = Field(
        default=False,
        description=(
            "Set to true to acknowledge that any remote controllers (e.g. "
            "Remora) have been flashed with the new payload."
        ),
    )


class DeployResponse(BaseModel):
    """Response of ``POST /deploy``."""

    status: str = Field(..., description="Outcome summary")
    message: str = Field(..., description="Human-readable deployment summary")
    deployed: List[str] = Field(
        default_factory=list, description="Filenames copied into active/"
    )
    machine_name: Optional[str] = Field(
        default=None, description="Machine name detected after deployment"
    )


class MachineNameResponse(BaseModel):
    """Response of ``GET /machine-name``."""

    machine_name: Optional[str] = Field(
        default=None, description="Machine name from active/<first>.ini's [EMC] section"
    )


# ---------------------------------------------------------------------- #
# Helpers                                                                 #
# ---------------------------------------------------------------------- #


def _build_compiler_marker_probe():
    """Return a callable ``(path) -> bool`` that uses the default compiler's marker."""
    try:
        default_compiler = compiler_registry.get(
            compiler_registry.ids()[0] if compiler_registry.ids() else ""
        )
    except (IndexError, KeyError):
        return None
    return default_compiler.has_source_marker


def _require_compiler(compiler_id: str):
    if compiler_id not in compiler_registry:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown compiler '{compiler_id}'. Known: {compiler_registry.ids()}",
        )
    return compiler_registry.get(compiler_id)


def _resolve_profile_path(profile_path: str) -> Path:
    """Validate ``profile_path`` and return an absolute path under profiles/."""
    if not profile_path:
        raise HTTPException(status_code=400, detail="profile_path is required.")
    try:
        return filesystem.safe_join(filesystem.PROFILES_DIR, profile_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _require_settings_overrides() -> Dict[str, bool]:
    """Return module settings overrides used by the endpoints.

    The router reads via the registry-mounted settings surface when
    available; the v1 stub keeps the defaults reachable as a fallback
    so the module is functional without a populated settings store.
    """
    from .settings import MachineConfigSettings

    defaults = MachineConfigSettings().model_dump()
    return defaults  # type: ignore[return-value]


# ---------------------------------------------------------------------- #
# Profiles CRUD                                                           #
# ---------------------------------------------------------------------- #


@router.get(
    "/profiles/tree",
    summary="List profiles tree",
    description="Flat listing of every file/folder under machine_config/profiles.",
    response_model=DirectoryListing,
)
def get_profiles_tree() -> DirectoryListing:
    """Return the entire ``profiles/`` tree as a flat list."""
    filesystem.ensure_directories()
    probe = _build_compiler_marker_probe()
    entries = filesystem.list_tree(filesystem.PROFILES_DIR, has_marker=probe)
    return DirectoryListing(
        root="profiles",
        entries=[DirectoryEntryModel(**e.to_dict()) for e in entries],
    )


@router.get(
    "/profiles/content/{path:path}",
    summary="Read a profile file",
    description="Return the raw text content of a file inside machine_config/profiles.",
    response_model=ProfileContent,
)
def read_profile(path: str) -> ProfileContent:
    """Read a profile file by relative path."""
    target = _resolve_profile_path(path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Profile not found: {path}")
    return ProfileContent(
        path=path,
        content=target.read_text(encoding="utf-8", errors="replace"),
    )


@router.put(
    "/profiles/content/{path:path}",
    summary="Save a profile file",
    description="Overwrite the content of a profile file inside machine_config/profiles.",
    response_model=StatusMessage,
)
def save_profile(path: str, payload: ProfileWriteRequest) -> StatusMessage:
    """Persist ``payload.content`` to ``profiles/<path>``."""
    target = _resolve_profile_path(path)
    if target.exists() and not target.is_file():
        raise HTTPException(status_code=400, detail=f"Not a file: {path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload.content, encoding="utf-8")
    return StatusMessage(status="ok", message=f"Saved {path}")


@router.post(
    "/profiles/folder",
    summary="Create a profiles folder",
    description="Create a folder (and any missing parents) under machine_config/profiles.",
    response_model=StatusMessage,
)
def create_folder(payload: CreateEntryRequest) -> StatusMessage:
    target = _resolve_profile_path(payload.path)
    if target.exists():
        raise HTTPException(status_code=409, detail=f"Already exists: {payload.path}")
    target.mkdir(parents=True, exist_ok=False)
    return StatusMessage(status="ok", message=f"Created folder {payload.path}")


@router.post(
    "/profiles/file",
    summary="Create a profiles file",
    description="Create an empty (or stub-seeded) file under machine_config/profiles.",
    response_model=StatusMessage,
)
def create_file(payload: CreateEntryRequest) -> StatusMessage:
    target = _resolve_profile_path(payload.path)
    if target.exists():
        raise HTTPException(status_code=409, detail=f"Already exists: {payload.path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("", encoding="utf-8")
    return StatusMessage(status="ok", message=f"Created file {payload.path}")


@router.put(
    "/profiles/rename",
    summary="Rename a profiles entry",
    description="Rename a file or folder under machine_config/profiles.",
    response_model=StatusMessage,
)
def rename_profile(payload: RenameRequest) -> StatusMessage:
    source = _resolve_profile_path(payload.source)
    destination = _resolve_profile_path(payload.destination)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {payload.source}")
    if destination.exists():
        raise HTTPException(status_code=409, detail=f"Already exists: {payload.destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.rename(destination)
    return StatusMessage(
        status="ok", message=f"Renamed {payload.source} -> {payload.destination}"
    )


@router.delete(
    "/profiles/{path:path}",
    summary="Delete a profiles entry",
    description="Delete a file or empty folder under machine_config/profiles.",
    response_model=StatusMessage,
)
def delete_profile(path: str) -> StatusMessage:
    target = _resolve_profile_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {path}")
    if target.is_dir():
        # Issue #41 keeps the helper simple — empty folders only. A
        # populated folder deletion would need a recursive helper,
        # but the UI button never offers that, so the call site can
        # only delete via two-step "delete children first" anyway.
        try:
            target.rmdir()
        except OSError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Folder is not empty; remove contents first: {path}",
            ) from exc
        return StatusMessage(status="ok", message=f"Deleted folder {path}")
    target.unlink()
    return StatusMessage(status="ok", message=f"Deleted file {path}")


# ---------------------------------------------------------------------- #
# Compilers                                                               #
# ---------------------------------------------------------------------- #


@router.get(
    "/compilers",
    summary="List registered compilers",
    description="Return every compiler currently registered in the machineconfig registry.",
    response_model=CompilerListResponse,
)
def list_compilers() -> CompilerListResponse:
    """Return every registered compiler in stable (id-sorted) order."""
    compilers = [
        CompilerSummary(
            id=c.id,
            title=c.title,
            source_marker=c.source_marker,
        )
        for c in compiler_registry.all()
    ]
    return CompilerListResponse(compilers=compilers)


# ---------------------------------------------------------------------- #
# Compile                                                                 #
# ---------------------------------------------------------------------- #


@router.post(
    "/compile",
    summary="Compile a profile",
    description=(
        "Run the named compiler against the given profile and stage the "
        "resulting artifacts into machine_config/ready_for_deploy."
    ),
    response_model=CompileResponse,
)
def compile_profile(payload: CompileRequest) -> CompileResponse:
    """Compile a profile and refresh the staged payload."""
    compiler = _require_compiler(payload.compiler_id)
    source = _resolve_profile_path(payload.profile_path)
    if not source.exists() or not source.is_file():
        raise HTTPException(
            status_code=404, detail=f"Profile not found: {payload.profile_path}"
        )

    filesystem.ensure_directories()
    filesystem.clear_directory(filesystem.STAGED_DIR)

    try:
        artifact_paths = compiler.compile(source, filesystem.STAGED_DIR)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        logger.error("Compile failed for %s: %s", payload.profile_path, exc)
        raise HTTPException(status_code=500, detail=f"Compile failed: {exc}") from exc

    settings = _require_settings_overrides()
    if settings.get("auto_readonly_after_stage", True):
        filesystem.mark_staged_readonly(filesystem.STAGED_DIR)

    staged_files = [
        StagedFile(name=p.name, size_bytes=p.stat().st_size)
        for p in filesystem.STAGED_DIR.iterdir()
        if p.is_file()
    ]
    staged_files.sort(key=lambda s: s.name)

    return CompileResponse(
        status="ok",
        compiler=compiler.id,
        profile=payload.profile_path,
        artifacts=[p.name for p in artifact_paths],
        staged=staged_files,
    )


# ---------------------------------------------------------------------- #
# Staged / Active (read-only)                                             #
# ---------------------------------------------------------------------- #


@router.get(
    "/staged",
    summary="List staged artifacts",
    description="Return every file currently sitting in machine_config/ready_for_deploy.",
    response_model=List[StagedFile],
)
def list_staged() -> List[StagedFile]:
    """Return the staged artifact list."""
    filesystem.ensure_directories()
    if not filesystem.STAGED_DIR.exists():
        return []
    files = [
        StagedFile(name=p.name, size_bytes=p.stat().st_size)
        for p in sorted(filesystem.STAGED_DIR.iterdir(), key=lambda p: p.name)
        if p.is_file()
    ]
    return files


@router.get(
    "/staged/content/{name}",
    summary="Read a staged file",
    description="Return the raw text content of a file in machine_config/ready_for_deploy.",
    response_model=StagedContent,
)
def read_staged(name: str) -> StagedContent:
    """Return the content of a single staged file. Read-only."""
    target = filesystem.safe_join(filesystem.STAGED_DIR, name)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Staged file not found: {name}")
    return StagedContent(
        name=name,
        content=target.read_text(encoding="utf-8", errors="replace"),
        read_only=True,
    )


@router.get(
    "/active",
    summary="List active artifacts",
    description=(
        "Return every file in machine_config/active plus the current "
        "machine name extracted from the active INI."
    ),
    response_model=ActiveListing,
)
def list_active() -> ActiveListing:
    """Return the active artifact list + machine name."""
    filesystem.ensure_directories()
    files: List[ActiveFile] = []
    if filesystem.ACTIVE_DIR.exists():
        for path in sorted(filesystem.ACTIVE_DIR.iterdir(), key=lambda p: p.name):
            if path.is_file():
                files.append(ActiveFile(name=path.name, size_bytes=path.stat().st_size))
    machine_name = filesystem.parse_machine_name(filesystem.ACTIVE_DIR)
    return ActiveListing(machine_name=machine_name, files=files)


@router.get(
    "/active/content/{name}",
    summary="Read an active file",
    description="Return the raw text content of a file in machine_config/active.",
    response_model=ActiveContent,
)
def read_active(name: str) -> ActiveContent:
    """Return the content of a single active file."""
    target = filesystem.safe_join(filesystem.ACTIVE_DIR, name)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Active file not found: {name}")
    return ActiveContent(
        name=name,
        content=target.read_text(encoding="utf-8", errors="replace"),
    )


# ---------------------------------------------------------------------- #
# Deploy                                                                  #
# ---------------------------------------------------------------------- #


@router.post(
    "/deploy",
    summary="Deploy staged artifacts",
    description=(
        "Promote the staged artifacts from machine_config/ready_for_deploy "
        "into machine_config/active. When ``require_confirm_flash`` is "
        "enabled in module settings, the request must include "
        "``confirm_flash=true`` (used by Remora and similar remote "
        "controllers to acknowledge that the board has been flashed)."
    ),
    response_model=DeployResponse,
)
def deploy_staged(payload: DeployRequest) -> DeployResponse:
    """Deploy the staged payload into the active directory."""
    settings = _require_settings_overrides()
    require_flash = bool(settings.get("require_confirm_flash", True))
    if require_flash and not payload.confirm_flash:
        raise HTTPException(
            status_code=400,
            detail=(
                "confirm_flash must be true to deploy. Acknowledge that any "
                "remote controllers (e.g. Remora) have been flashed first."
            ),
        )

    filesystem.ensure_directories()
    if not filesystem.STAGED_DIR.exists() or not any(filesystem.STAGED_DIR.iterdir()):
        raise HTTPException(
            status_code=400,
            detail="Staging area is empty. Compile a profile before deploying.",
        )

    filesystem.clear_directory(filesystem.ACTIVE_DIR)
    deployed = filesystem.copy_tree(filesystem.STAGED_DIR, filesystem.ACTIVE_DIR)
    machine_name = filesystem.parse_machine_name(filesystem.ACTIVE_DIR)

    return DeployResponse(
        status="ok",
        message=f"Deployed {len(deployed)} artifacts into machine_config/active.",
        deployed=deployed,
        machine_name=machine_name,
    )


@router.get(
    "/machine-name",
    summary="Read current machine name",
    description=(
        "Best-effort detection of the current machine name from the first "
        "INI file under machine_config/active. Returns null when the "
        "active directory is empty."
    ),
    response_model=MachineNameResponse,
)
def get_machine_name() -> MachineNameResponse:
    """Return the current machine name, or ``None``."""
    filesystem.ensure_directories()
    return MachineNameResponse(
        machine_name=filesystem.parse_machine_name(filesystem.ACTIVE_DIR)
    )


__all__ = ["router"]