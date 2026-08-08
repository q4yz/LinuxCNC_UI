"""HTTP router for the machineconfig module.

Endpoint groups (mounted by the registry under
``/api/v1/modules/machineconfig``):

* **Profiles CRUD** — full hierarchical read/write of
  ``machine_config/profiles`` (list, read, write, create folder,
  create file, delete, rename). Backed by
  :class:`ConfigFileService`.
* **Compilers** — ``GET /compilers`` returns the registered compilers
  plus a marker probe (``has_marker``) per file under ``profiles``.
* **Compile** — ``POST /compile`` runs the selected compiler against
  a chosen profile and stages the artifacts into
  ``machine_config/ready_for_deploy``. Backed by
  :class:`StagedFileService.clear_and_stage`.
* **Staged / Active read-only** — ``GET /staged`` and
  ``GET /active`` plus per-file content endpoints. Operators can
  inspect the staged and active payloads but cannot edit them
  through this surface. Backed by :class:`StagedFileService` and
  :class:`ActiveFileService`.
* **Deploy** — ``POST /deploy`` promotes the staged payload into
  ``machine_config/active`` via
  :meth:`StagedFileService.deploy_to_active`. Accepts
  ``confirm_flash`` to satisfy remote-controller (e.g. Remora)
  workflows.
* **Machine name** — ``GET /machine-name`` reads the current machine
  name out of the active INI so the Active dashboard can render
  the "currently running machine" header. Backed by
  :meth:`ActiveFileService.machine_name`.

The router is intentionally a thin HTTP wrapper: every filesystem
operation is delegated to the corresponding service. The
``_build_compiler_marker_probe`` helper stays here because
mapping compilers to marker detection is a compiler-registry
concern, not a filesystem concern.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services import (
    ActiveFileService,
    ConfigFileService,
    StagedFileService,
    get_active_service,
    get_config_service,
    get_staged_service,
)
from .compilers import registry as compiler_registry
from .parser import ConfigValidationError

logger = logging.getLogger("backend.modules.machineconfig.router")

router = APIRouter(tags=["modules:machineconfig"])


# ---------------------------------------------------------------------- #
# Structured-error exception handler                                      #
# ---------------------------------------------------------------------- #
#
# Compile-time validation errors (e.g. ``DuplicateStepperPinError``) are
# raised deep inside the compiler pipeline. Catching them at the
# ``compile_profile`` endpoint boundary would only catch *this*
# endpoint; the issue (and the operator-facing toast channel) expects
# the structured shape to be available everywhere a parser error can
# surface. A FastAPI exception handler covers the whole router at once.
#
# Response body shape (issue #99, acceptance criteria):
#
#     {
#         "error": {
#             "section": "<section name>",
#             "key":     "<keyword within section>",
#             "line":    <int | null>,
#             "message": "<human-readable message>",
#             "kind":    "<stable discriminator>"
#         }
#     }
#
# The ``message`` field is the same string the legacy ``detail`` field
# used to carry, so callers that previously read the error string can
# locate it via ``body.error.message``. The HTTP status is ``400`` for
# every :class:`ConfigValidationError` — the operator supplied invalid
# input; retrying without changes will keep failing.


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the structured-error handler to ``app``.

    Called from the module's :meth:`on_load` hook because
    :class:`APIRouter` does not expose ``add_exception_handler`` in
    this FastAPI version. The handler is registered against the
    :class:`ConfigValidationError` class so every subclass
    (``UndefinedKeywordError``, ``MissingRequiredKeywordError``,
    ``InvalidValueError``, ``UnknownStepperError``, and the new
    ``DuplicateStepperPinError``) is caught by the same code path.

    Idempotent: re-registering the same handler class on the same
    FastAPI app replaces the previous handler, so the call is safe
    under the ``--reload`` lifecycle.
    """

    app.add_exception_handler(
        ConfigValidationError, _config_validation_exception_handler
    )


async def _config_validation_exception_handler(
    request: Request, exc: ConfigValidationError
) -> JSONResponse:
    """Render :class:`ConfigValidationError` as a structured 4xx body.

    The handler is intentionally minimal — it never logs at WARN/ERROR
    because validation errors are operator-actionable, not server-side
    failures. ``logger.debug`` keeps a breadcrumb for the curious.
    """

    logger.debug(
        "ConfigValidationError on %s %s: %s",
        request.method,
        request.url.path,
        exc.to_dict(),
    )
    return JSONResponse(status_code=400, content={"error": exc.to_dict()})


# ---------------------------------------------------------------------- #
# Pydantic models                                                         #
# ---------------------------------------------------------------------- #


class StatusMessage(BaseModel):
    """Generic status + message response."""

    status: str = Field(..., description="Outcome summary (e.g. 'ok')")
    message: str = Field(..., description="Human-readable confirmation")


class DirectoryEntryModel(BaseModel):
    """Single node in a directory listing.

    Mirrors :class:`services.file_service.FileMetadata` but in the
    Pydantic shape the frontend codegen can type-check.
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
    read_only: bool = Field(
        default=False,
        description="True when the POSIX write bits are cleared on this entry",
    )
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
    """Payload returned by ``GET /profiles/content?path=<rel>``."""

    path: str = Field(..., description="Forward-slash path relative to profiles/")
    content: str = Field(..., description="Raw text content of the file")


class ProfileWriteRequest(BaseModel):
    """Body of ``PUT /profiles/content?path=<rel>``."""

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
    """Return a callable ``(path) -> bool`` that uses the default compiler's marker.

    Stays in the router because mapping compilers to marker
    detection is a compiler-registry concern, not a filesystem
    one. The probe is passed to :class:`ConfigFileService` so the
    ``has_marker`` flag is computed alongside the listing.
    """
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


def _resolve_profile_path(profile_path: str, service: ConfigFileService):
    """Validate ``profile_path`` and return an absolute path under profiles/."""
    if not profile_path:
        raise HTTPException(status_code=400, detail="profile_path is required.")
    try:
        return service.safe_join(profile_path)
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
    service: ConfigFileService = get_config_service()
    probe = _build_compiler_marker_probe()
    entries = service.list_files()
    if probe is not None:
        for entry in entries:
            if entry.kind == "file":
                try:
                    target = service.safe_join(entry.path)
                except ValueError:
                    entry.has_marker = False
                    continue
                try:
                    entry.has_marker = bool(probe(target))
                except Exception:  # noqa: BLE001 - intentional broad catch
                    entry.has_marker = False
    return DirectoryListing(
        root="profiles",
        entries=[DirectoryEntryModel(**e.to_dict()) for e in entries],
    )


@router.get(
    "/profiles/content",
    summary="Read a profile file",
    description=(
        "Return the raw text content of a file inside "
        "machine_config/profiles. The relative path is supplied "
        "as the ``path`` query parameter so URL-encoded slashes "
        "do not get stripped by the dev-server proxy."
    ),
    response_model=ProfileContent,
)
def read_profile(path: str) -> ProfileContent:
    """Read a profile file by relative path.

    ``path`` is a query parameter rather than a path segment —
    URL-encoded slashes (``%2F``) inside a path segment were being
    dropped by the Vite dev-server proxy. Query strings travel
    intact, so nested paths like ``machine/axis.cfg`` survive
    end-to-end.
    """
    service: ConfigFileService = get_config_service()
    try:
        content = service.read_file(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Profile not found: {path}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProfileContent(path=path, content=content)


@router.put(
    "/profiles/content",
    summary="Save a profile file",
    description=(
        "Overwrite the content of a profile file inside "
        "machine_config/profiles. The relative path is supplied "
        "as the ``path`` query parameter so URL-encoded slashes "
        "do not get stripped by the dev-server proxy."
    ),
    response_model=StatusMessage,
)
def save_profile(path: str, payload: ProfileWriteRequest) -> StatusMessage:
    """Persist ``payload.content`` to ``profiles/<path>``.

    Same query-parameter rationale as :func:`read_profile`.
    """
    service: ConfigFileService = get_config_service()
    try:
        service.write_file(path, payload.content, overwrite=True)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusMessage(status="ok", message=f"Saved {path}")


@router.post(
    "/profiles/folder",
    summary="Create a profiles folder",
    description="Create a folder (and any missing parents) under machine_config/profiles.",
    response_model=StatusMessage,
)
def create_folder(payload: CreateEntryRequest) -> StatusMessage:
    service: ConfigFileService = get_config_service()
    try:
        service.create_directory(payload.path)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=f"Already exists: {payload.path}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusMessage(status="ok", message=f"Created folder {payload.path}")


@router.post(
    "/profiles/file",
    summary="Create a profiles file",
    description="Create an empty (or stub-seeded) file under machine_config/profiles.",
    response_model=StatusMessage,
)
def create_file(payload: CreateEntryRequest) -> StatusMessage:
    service: ConfigFileService = get_config_service()
    try:
        service.write_file(payload.path, "", overwrite=False)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=f"Already exists: {payload.path}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusMessage(status="ok", message=f"Created file {payload.path}")


@router.post(
    "/profiles/upload",
    summary="Upload a profile file",
    description=(
        "Upload a file into a directory under machine_config/profiles. "
        "The relative path is supplied as the ``path`` query parameter."
    ),
    response_model=StatusMessage,
)
async def upload_profile(path: str, file: UploadFile = File(...)) -> StatusMessage:
    service: ConfigFileService = get_config_service()
    try:
        service.write_bytes(path, await file.read(), overwrite=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusMessage(status="ok", message=f"Uploaded {path}")


@router.put(
    "/profiles/rename",
    summary="Rename a profiles entry",
    description="Rename a file or folder under machine_config/profiles.",
    response_model=StatusMessage,
)
def rename_profile(payload: RenameRequest) -> StatusMessage:
    service: ConfigFileService = get_config_service()
    try:
        service.rename(payload.source, payload.destination)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Not found: {payload.source}") from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=f"Already exists: {payload.destination}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusMessage(
        status="ok", message=f"Renamed {payload.source} -> {payload.destination}"
    )


@router.delete(
    "/profiles/entry",
    summary="Delete a profiles entry",
    description=(
        "Delete a file or empty folder under machine_config/profiles. "
        "The relative path is supplied as the ``path`` query "
        "parameter. The ``/entry`` suffix avoids a bare "
        "``DELETE /profiles`` endpoint, which is semantically "
        "confusing next to the listing endpoint."
    ),
    response_model=StatusMessage,
)
def delete_profile(path: str) -> StatusMessage:
    service: ConfigFileService = get_config_service()
    try:
        service.delete(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Not found: {path}") from exc
    except IsADirectoryError as exc:
        # ``FileService.delete`` raises ``IsADirectoryError`` when the
        # folder still has children — keep the legacy "remove contents
        # first" wording so the frontend toast stays informative.
        raise HTTPException(
            status_code=400,
            detail=f"Folder is not empty; remove contents first: {path}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusMessage(status="ok", message=f"Deleted {path}")


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
    config_service: ConfigFileService = get_config_service()
    staged_service: StagedFileService = get_staged_service()
    source = _resolve_profile_path(payload.profile_path, config_service)
    if not source.exists() or not source.is_file():
        raise HTTPException(
            status_code=404, detail=f"Profile not found: {payload.profile_path}"
        )

    try:
        artifact_paths = staged_service.clear_and_stage(compiler, source)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConfigValidationError:
        # Parser-level validation errors are routed through the
        # global exception handler registered in ``on_load``
        # (``register_exception_handlers``). The structured envelope
        # shape is the contract the frontend toast channel depends
        # on (issue #99). ``ConfigValidationError`` is a subclass of
        # ``ValueError`` so it MUST be caught before the
        # ``ValueError`` branch below — reordering the clauses would
        # silently swallow the structured response.
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        logger.error("Compile failed for %s: %s", payload.profile_path, exc)
        raise HTTPException(status_code=500, detail=f"Compile failed: {exc}") from exc

    settings = _require_settings_overrides()
    if settings.get("auto_readonly_after_stage", True):
        staged_service.mark_read_only()

    staged_files = [
        StagedFile(name=entry.name, size_bytes=entry.size_bytes)
        for entry in staged_service.list_files()
        if entry.kind == "file"
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
    service: StagedFileService = get_staged_service()
    files = [
        StagedFile(name=entry.name, size_bytes=entry.size_bytes)
        for entry in service.list_files()
        if entry.kind == "file"
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
    service: StagedFileService = get_staged_service()
    try:
        content = service.read_file(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Staged file not found: {name}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StagedContent(name=name, content=content, read_only=True)


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
    service: ActiveFileService = get_active_service()
    files = [
        ActiveFile(name=entry.name, size_bytes=entry.size_bytes)
        for entry in service.list_active_files()
    ]
    return ActiveListing(machine_name=service.machine_name(), files=files)


@router.get(
    "/active/content/{name}",
    summary="Read an active file",
    description="Return the raw text content of a file in machine_config/active.",
    response_model=ActiveContent,
)
def read_active(name: str) -> ActiveContent:
    """Return the content of a single active file."""
    service: ActiveFileService = get_active_service()
    try:
        content = service.read_file(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Active file not found: {name}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ActiveContent(name=name, content=content)


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

    staged_service: StagedFileService = get_staged_service()
    active_service: ActiveFileService = get_active_service()

    try:
        deployed = staged_service.deploy_to_active(active_service)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    machine_name = active_service.machine_name()

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
    service: ActiveFileService = get_active_service()
    return MachineNameResponse(machine_name=service.machine_name())


__all__ = ["router"]
