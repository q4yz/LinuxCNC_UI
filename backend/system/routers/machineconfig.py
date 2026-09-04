"""HTTP router for the machineconfig module.

Endpoint groups (mounted by the registry under
``/api/v1/modules/machineconfig``):

* **Profiles CRUD** — full hierarchical read/write of
  ``machine_config/profiles`` (list, read, write, create folder,
  create file, delete, rename). Backed by
  :class:`ConfigFileService`. Each listed file also carries
  ``has_marker`` — whether it contains the ``#Start`` token, a purely
  cosmetic readiness badge in the frontend explorer.
* **Machines (template generation + CRUD)** — ``POST
  /machines/generate`` parses a profile and writes the per-machine
  template set (``machine.cfg``, ``hardware.json``, ``machine.ini``,
  ``machine.hal``, ``custom.hal``, ``webgui_connections.hal``,
  ``tool.tbl``) under ``machine_config/machines/<name>/configs/``;
  the remaining ``/machines/...`` endpoints mirror the profiles CRUD
  surface for hand-editing the generated templates. Backed by
  :mod:`services.machinetemplates`.
* **Staged / Active read-only** — ``GET /active`` plus per-file
  content endpoints report what's currently deployed. Backed by
  :class:`ActiveFileService`.
* **Deploy** — ``POST /deploy`` promotes a generated machine's
  templates (``machine_config/machines/<name>/configs/``) into
  ``machine_config/active`` via :meth:`ActiveFileService.deploy_from`.
  This only stages files on disk — it does not touch the running
  ``linuxcnc`` process; use ``POST /api/v1/system/machine/switch``
  (in the system service's machine-lifecycle router) to deploy *and*
  restart in one call.
* **Machine name** — ``GET /machine-name`` reads the current machine
  name out of the active INI so the Active dashboard can render
  the "currently running machine" header. Backed by
  :meth:`ActiveFileService.machine_name`.
* **M-codes** — ``GET/PUT/DELETE /m-codes/...`` exposes the bare
  ``M<num>`` files under ``machine_config/m_codes/`` so the
  universal editor can edit them the same way it edits
  ``.cfg`` / ``.ini`` profiles. Backed by
  :class:`MCodeFileService` (same instance the macros module's
  ``?kind=mcode`` path uses).

The router is intentionally a thin HTTP wrapper: every filesystem
operation is delegated to the corresponding service.

A previous revision of this router also exposed a pluggable
``Compiler`` framework (``GET /compilers``, ``POST /compile``,
``GET /staged`` + content) that translated a profile into a Remora
``config.txt`` flash payload staged under
``machine_config/ready_for_deploy``. That framework — and the
Remora-specific flashing concept generally — has been retired in
favour of the template generator above; see ``.agent/HANDOFF.md``
for the removal notes.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Body, FastAPI, HTTPException, Path, Query, Request, Response, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from exceptions import BadRequestError, ConflictError, NotFoundError
from services import (
    ActiveFileService,
    ConfigFileService,
    MCodeFileService,
    MachineFileService,
    get_active_service,
    get_config_service,
    get_machine_service,
    get_mcode_service,
)
from services.machinetemplates import (
    MachineExistsError,
    generate_machine_templates,
    resolve_machine_configs_dir,
)
from machineconfig_parser import ConfigValidationError

logger = logging.getLogger("backend.machineconfig_service")

router = APIRouter(
    prefix="/api/v1/modules/machineconfig",
    tags=["modules:machineconfig"],
)


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


class MCodeEntry(BaseModel):
    """One row of ``GET /m-codes/list``.

    Mirrors :class:`MacroListItem` so the frontend can re-use its
    listing reducer. ``path`` is the bare ``M<num>`` token — the
    filesystem path is implicit (the m-codes root resolved against
    the project).
    """

    name: str = Field(..., description="Bare M-code token, e.g. M101")
    kind: str = Field(default="mcode", description="Always 'mcode'.")
    size_bytes: int = Field(..., description="On-disk byte size")


class MCodeListResponse(BaseModel):
    """Response body of ``GET /m-codes/list``."""

    mcodes: List[MCodeEntry] = Field(
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

    machine_path: str = Field(
        ...,
        description=(
            "Path under machine_config/machines to a generated machine "
            "(e.g. 'PrintNC' or 'PrintNC/configs') — generate it first "
            "with POST /machines/generate."
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


# ---------------------------------------------------------------------- #
# Helpers                                                                 #
# ---------------------------------------------------------------------- #


#: Marker substring flagging a profile as "ready" — purely a cosmetic
#: badge in the frontend explorer (``ProfilesExplorer.vue``) today;
#: no endpoint gates on it. Matches the historical compiler default.
PROFILE_MARKER = "#Start"


def _has_marker(path, *, max_bytes: int = 8192) -> bool:
    """Return ``True`` when ``path`` contains :data:`PROFILE_MARKER`.

    Reads only the first ``max_bytes`` of the file so a large config
    doesn't pay a full scan.
    """
    if not path.is_file() or path.suffix.lower() != ".cfg":
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(max_bytes)
    except OSError:
        return False
    return PROFILE_MARKER in head


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
    entries = service.list_files()
    for entry in entries:
        if entry.kind != "file":
            continue
        try:
            target = service.safe_join(entry.path)
        except ValueError:
            entry.has_marker = False
            continue
        entry.has_marker = _has_marker(target)
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
        raise NotFoundError(f"Profile not found: {path}") from exc
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
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
        raise BadRequestError(str(exc)) from exc
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
        raise ConflictError(f"Already exists: {payload.path}") from exc
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
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
        raise ConflictError(f"Already exists: {payload.path}") from exc
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
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
        raise BadRequestError(str(exc)) from exc
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
        raise NotFoundError(f"Not found: {payload.source}") from exc
    except FileExistsError as exc:
        raise ConflictError(f"Already exists: {payload.destination}") from exc
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
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
        raise NotFoundError(f"Not found: {path}") from exc
    except IsADirectoryError as exc:
        # ``FileService.delete`` raises ``IsADirectoryError`` when the
        # folder still has children — keep the legacy "remove contents
        # first" wording so the frontend toast stays informative.
        raise BadRequestError(f"Folder is not empty; remove contents first: {path}") from exc
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    return StatusMessage(status="ok", message=f"Deleted {path}")


# ---------------------------------------------------------------------- #
# Machines (template generation + CRUD)                                   #
# ---------------------------------------------------------------------- #
#
# The template-based replacement for the deprecated compiler. A profile
# generates a per-machine template set under ``machine_config/machines/``
# (machine.cfg copy, hardware.json, machine.ini + machine.hal templates).
# Every endpoint mirrors the profiles CRUD so the frontend explorer is a
# like-for-like clone. Files here are templates — writable on purpose.


@router.get(
    "/machines/tree",
    summary="List machines tree",
    description="Flat listing of every file/folder under machine_config/machines.",
    response_model=DirectoryListing,
)
def get_machines_tree() -> DirectoryListing:
    """Return the entire ``machines/`` tree as a flat list."""
    service: MachineFileService = get_machine_service()
    entries = service.list_files()
    return DirectoryListing(
        root="machines",
        entries=[DirectoryEntryModel(**e.to_dict()) for e in entries],
    )


@router.post(
    "/machines/generate",
    summary="Generate machine templates",
    description=(
        "Generate the per-machine template set from a profile into "
        "machine_config/machines/<target_folder>/<stem>/configs/: a "
        "verbatim machine.cfg copy, the real hardware.json, and the "
        "machine.ini / machine.hal templates (config.txt is intentionally "
        "not generated). Answers 409 when the machine already exists "
        "unless confirm_override is set."
    ),
    response_model=GenerateResponse,
)
def generate_machine(payload: GenerateRequest) -> GenerateResponse:
    """Generate templates for ``payload.profile_path`` into machines/."""
    try:
        result = generate_machine_templates(
            payload.profile_path,
            target_folder=payload.target_folder or "",
            confirm_override=payload.confirm_override,
            config_service=get_config_service(),
            machine_service=get_machine_service(),
        )
    except FileNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except MachineExistsError as exc:
        # Structured 409: the frontend opens the "machine already
        # exists — override?" confirm modal off ``kind`` and retries
        # with ``confirm_override: true``.
        raise HTTPException(
            status_code=409,
            detail={
                "kind": "machine_exists",
                "machine": exc.machine,
                "existing": exc.existing_files,
                "message": (
                    f"Machine '{exc.machine}' already exists. "
                    "Confirm to override the existing configuration."
                ),
            },
        ) from exc
    except ConfigValidationError:
        # Structured parser envelope via the global handler (see
        # the compile endpoint for the ordering rationale).
        raise
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc

    machine_service: MachineFileService = get_machine_service()
    files: List[MachineFile] = []
    for rel in result.files:
        try:
            target = machine_service.safe_join(rel)
            size = target.stat().st_size if target.is_file() else 0
        except ValueError:
            size = 0
        files.append(
            MachineFile(name=rel.rsplit("/", 1)[-1], path=rel, size_bytes=size)
        )

    return GenerateResponse(
        status="ok",
        machine=result.machine,
        target_folder=result.target_folder,
        files=files,
    )


@router.get(
    "/machines/content",
    summary="Read a machine file",
    description=(
        "Return the raw text content of a file inside "
        "machine_config/machines. The relative path is supplied "
        "as the ``path`` query parameter so URL-encoded slashes "
        "do not get stripped by the dev-server proxy."
    ),
    response_model=ProfileContent,
)
def read_machine_file(path: str) -> ProfileContent:
    service: MachineFileService = get_machine_service()
    try:
        content = service.read_file(path)
    except FileNotFoundError as exc:
        raise NotFoundError(f"Machine file not found: {path}") from exc
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    return ProfileContent(path=path, content=content)


@router.put(
    "/machines/content",
    summary="Save a machine file",
    description=(
        "Overwrite the content of a file inside machine_config/machines. "
        "Machine files are templates — writable by design."
    ),
    response_model=StatusMessage,
)
def save_machine_file(path: str, payload: ProfileWriteRequest) -> StatusMessage:
    service: MachineFileService = get_machine_service()
    try:
        service.write_file(path, payload.content, overwrite=True)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    return StatusMessage(status="ok", message=f"Saved {path}")


@router.post(
    "/machines/folder",
    summary="Create a machines folder",
    description="Create a folder (and any missing parents) under machine_config/machines.",
    response_model=StatusMessage,
)
def create_machine_folder(payload: CreateEntryRequest) -> StatusMessage:
    service: MachineFileService = get_machine_service()
    try:
        service.create_directory(payload.path)
    except FileExistsError as exc:
        raise ConflictError(f"Already exists: {payload.path}") from exc
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    return StatusMessage(status="ok", message=f"Created folder {payload.path}")


@router.post(
    "/machines/file",
    summary="Create a machines file",
    description="Create an empty file under machine_config/machines.",
    response_model=StatusMessage,
)
def create_machine_file(payload: CreateEntryRequest) -> StatusMessage:
    service: MachineFileService = get_machine_service()
    try:
        service.write_file(payload.path, "", overwrite=False)
    except FileExistsError as exc:
        raise ConflictError(f"Already exists: {payload.path}") from exc
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    return StatusMessage(status="ok", message=f"Created file {payload.path}")


@router.post(
    "/machines/upload",
    summary="Upload a machines file",
    description=(
        "Upload a file into a directory under machine_config/machines. "
        "The relative path is supplied as the ``path`` query parameter."
    ),
    response_model=StatusMessage,
)
async def upload_machine_file(path: str, file: UploadFile = File(...)) -> StatusMessage:
    service: MachineFileService = get_machine_service()
    try:
        service.write_bytes(path, await file.read(), overwrite=True)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    return StatusMessage(status="ok", message=f"Uploaded {path}")


@router.put(
    "/machines/rename",
    summary="Rename a machines entry",
    description="Rename a file or folder under machine_config/machines.",
    response_model=StatusMessage,
)
def rename_machine_entry(payload: RenameRequest) -> StatusMessage:
    service: MachineFileService = get_machine_service()
    try:
        service.rename(payload.source, payload.destination)
    except FileNotFoundError as exc:
        raise NotFoundError(f"Not found: {payload.source}") from exc
    except FileExistsError as exc:
        raise ConflictError(f"Already exists: {payload.destination}") from exc
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    return StatusMessage(
        status="ok", message=f"Renamed {payload.source} -> {payload.destination}"
    )


@router.delete(
    "/machines/entry",
    summary="Delete a machines entry",
    description=(
        "Delete a file or empty folder under machine_config/machines. "
        "The relative path is supplied as the ``path`` query parameter."
    ),
    response_model=StatusMessage,
)
def delete_machine_entry(path: str) -> StatusMessage:
    service: MachineFileService = get_machine_service()
    try:
        service.delete(path)
    except FileNotFoundError as exc:
        raise NotFoundError(f"Not found: {path}") from exc
    except IsADirectoryError as exc:
        raise BadRequestError(f"Folder is not empty; remove contents first: {path}") from exc
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    return StatusMessage(status="ok", message=f"Deleted {path}")


# ---------------------------------------------------------------------- #
# Active (read-only)                                                      #
# ---------------------------------------------------------------------- #


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
        raise NotFoundError(f"Active file not found: {name}") from exc
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    return ActiveContent(name=name, content=content)


# ---------------------------------------------------------------------- #
# Deploy                                                                  #
# ---------------------------------------------------------------------- #


@router.post(
    "/deploy",
    summary="Deploy a generated machine",
    description=(
        "Promote a generated machine's templates from "
        "machine_config/machines/<name>/configs into machine_config/active. "
        "This only stages files on disk — it does not touch the running "
        "linuxcnc process; use POST /api/v1/system/machine/switch to "
        "deploy and restart in one call."
    ),
    response_model=DeployResponse,
    responses={404: {"description": "Machine not found."}},
)
def deploy_machine(payload: DeployRequest) -> DeployResponse:
    """Deploy a generated machine's templates into the active directory."""
    machine_service: MachineFileService = get_machine_service()
    active_service: ActiveFileService = get_active_service()

    try:
        configs_dir = resolve_machine_configs_dir(machine_service, payload.machine_path)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    if not configs_dir.exists() or not configs_dir.is_dir():
        raise NotFoundError(f"Machine not found: {payload.machine_path}")

    deployed = active_service.deploy_from(configs_dir)
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


# ---------------------------------------------------------------------- #
# M-code endpoints                                                         #
# ---------------------------------------------------------------------- #
#
# The macros module fronts these files through ``?kind=mcode`` and
# ``ModulesMacrosService``. The mirror surface under the machineconfig
# router exists so the **universal editor** can read / write M-codes
# the same way it reads / writes ``.cfg`` / ``.ini`` files — the
# ``isProfilePath`` branch for ``^M\d+$`` names points at these
# endpoints. Both routes delegate to the same
# :class:`MCodeFileService`, so a single source-of-truth owns the
# filesystem state.
#
# Name validation is the strict ``M100.M199`` range
# (regex ``^M1\d{2}$``). Out-of-range names return ``400`` here and
# ``400`` from the macros router; the regex and the
# :class:`MCodeFileService.mcode_filter` listing filter must agree.


_MCODE_NAME_PATTERN = MCodeFileService.MCODE_NAME


def _validate_mcode_name(name: str) -> str:
    """Return ``name`` if it matches the ``M100.M199`` regex.

    Raises:
        HTTPException: ``400`` for anything that doesn't match.
    """
    if not _MCODE_NAME_PATTERN.match(name):
        raise BadRequestError(
            f"invalid M-code name: {name!r} "
            "(must match ^M1\\d{2}$ — i.e. M100.M199)"
        )
    return name


@router.get(
    "/m-codes/list",
    summary="List M-codes",
    description=(
        "Return every ``M<num>`` file under ``machine_config/m_codes/`` "
        "(LinuxCNC's ``USER_M_PATH``). Sorted by name."
    ),
    response_model=MCodeListResponse,
    operation_id="listMCodes",
)
def list_mcodes() -> MCodeListResponse:
    """List M-codes via :class:`MCodeFileService`."""
    service: MCodeFileService = get_mcode_service()
    entries = [
        MCodeEntry(name=entry.name, size_bytes=entry.size_bytes)
        for entry in service.list_files()
        if entry.kind == "file"
    ]
    entries.sort(key=lambda entry: entry.name)
    return MCodeListResponse(mcodes=entries)


@router.get(
    "/m-codes/content",
    summary="Read M-code content",
    description=(
        "Return the raw text content of the requested ``M<num>`` "
        "file. The query parameter carries the bare name (no "
        "path / no extension). Returns ``404`` for missing files "
        "and ``400`` for out-of-range names."
    ),
    operation_id="readMCode",
    response_model=MCodeContentResponse,
    responses={
        400: {"description": "Invalid M-code name."},
        404: {"description": "No M-code with that name."},
    },
)
def read_mcode(
    path: str = Query(
        ...,
        description="Bare M-code name, e.g. ``M101``. Must match ``^M1\\d{2}$``.",
    ),
) -> MCodeContentResponse:
    """Read a single M-code file by relative name."""
    _validate_mcode_name(path)
    service: MCodeFileService = get_mcode_service()
    try:
        target = service.safe_join(path)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    if not target.exists():
        raise NotFoundError(f"M-code not found: {path}")
    return MCodeContentResponse(path=path, content=target.read_text(encoding="utf-8"))


@router.put(
    "/m-codes/content",
    summary="Write M-code content",
    description=(
        "Persist ``payload.content`` atomically as the requested "
        "``M<num>`` file. The body is the raw text content (UTF-8). "
        "Returns ``400`` for an out-of-range name and ``422`` for "
        "a zero-byte payload — the latter mirrors the macros "
        "router's FastAPI behaviour and is normalised by the "
        "frontend (``\\\\n`` sentinel)."
    ),
    operation_id="writeMCode",
    response_model=MCodeStatusMessage,
    responses={
        400: {"description": "Invalid M-code name."},
        422: {"description": "Zero-byte payload."},
    },
)
def write_mcode(
    payload: MCodeWriteRequest = Body(...),
    path: str = Query(
        ...,
        description="Bare M-code name, e.g. ``M101``. Must match ``^M1\\d{2}$``.",
    ),
) -> MCodeStatusMessage:
    """Write an M-code file atomically."""
    _validate_mcode_name(path)
    service: MCodeFileService = get_mcode_service()
    try:
        service.write_file(path, payload.content)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    # :meth:`FileService.write_file` returns ``None`` (stdlib
    # ``Path.write_text`` parity); the byte size is read off the
    # on-disk stat. ``target.exists()`` is checked so a vanished
    # file surfaces as ``0 bytes`` rather than an exception.
    target = service.safe_join(path)
    size = target.stat().st_size if target.exists() else 0
    return MCodeStatusMessage(
        status="ok",
        message=f"Saved {path} ({size} bytes).",
    )


@router.delete(
    "/m-codes/{name}",
    summary="Delete M-code",
    description=(
        "Remove the named ``M<num>`` file from disk. Returns "
        "``204`` on success, ``404`` for missing, and ``400`` for "
        "out-of-range names."
    ),
    status_code=204,
    operation_id="deleteMCode",
    response_class=Response,
    responses={
        204: {"description": "M-code deleted."},
        404: {"description": "No M-code with that name."},
        400: {"description": "Invalid M-code name."},
    },
)
def delete_mcode(
    name: str = Path(
        ...,
        description="Bare M-code name, e.g. ``M101``. Must match ``^M1\\d{2}$``.",
    ),
) -> Response:
    """Delete the named M-code from disk."""
    _validate_mcode_name(name)
    service: MCodeFileService = get_mcode_service()
    try:
        target = service.safe_join(name)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    if not target.exists():
        raise NotFoundError(f"M-code not found: {name}")
    target.unlink()
    return Response(status_code=204)


__all__ = ["router"] 
