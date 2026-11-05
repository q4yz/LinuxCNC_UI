"""OctoPrint-compatible slicer API — send G-code from OrcaSlicer /
PrusaSlicer ("Physical printer", host type OctoPrint) or Cura (OctoPrint
Connection plugin) straight into ``nc_files/``.

Only the subset the slicers use (the same Moonraker emulates):

    GET  /api/version  /api/server  /api/settings  /api/printerprofiles
    GET  /api/printer  /api/job  /api/connection
    POST /api/login
    POST /api/files/local   multipart: file, path, select, print

Any API key is accepted (the slicers insist on sending one) — like the
rest of this UI, the API trusts the local network. ``select`` / ``print``
load the file into LinuxCNC when it runs; nothing is ever started
(``SlicerUploadService``). Lives in the always-up system service, so
files can be sent while the machine is off.
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from models.OctoPrintModels import (
    OctoConnection,
    OctoConnectionCurrent,
    OctoFileRefs,
    OctoJob,
    OctoLogin,
    OctoPrinter,
    OctoPrinterProfiles,
    OctoServer,
    OctoSettings,
    OctoState,
    OctoStateFlags,
    OctoUploadedFile,
    OctoUploadFiles,
    OctoUploadResponse,
    OctoVersion,
)
from services.SlicerUploadService import UnsupportedFileError, get_slicer_upload_service

router = APIRouter(prefix="/api", tags=["OctoPrint (slicer upload)"])


def _state_text() -> str:
    return "Operational" if get_slicer_upload_service().machine_running() else "Offline"


@router.get("/version", response_model=OctoVersion, operation_id="octoprintVersion",
            summary="OctoPrint version (slicer connection test)")
def version() -> OctoVersion:
    return OctoVersion()


@router.get("/server", response_model=OctoServer, operation_id="octoprintServer",
            summary="OctoPrint server info")
def server() -> OctoServer:
    return OctoServer()


@router.post("/login", response_model=OctoLogin, operation_id="octoprintLogin",
             summary="OctoPrint login (any API key is accepted)")
def login() -> OctoLogin:
    return OctoLogin()


@router.get("/settings", response_model=OctoSettings, operation_id="octoprintSettings",
            summary="OctoPrint settings (no SD card, no webcam)")
def settings() -> OctoSettings:
    return OctoSettings()


@router.get("/printerprofiles", response_model=OctoPrinterProfiles, operation_id="octoprintPrinterProfiles",
            summary="OctoPrint printer profiles (one default)")
def printer_profiles() -> OctoPrinterProfiles:
    return OctoPrinterProfiles()


@router.get("/printer", response_model=OctoPrinter, operation_id="octoprintPrinter",
            summary="OctoPrint printer state: Operational while LinuxCNC runs")
def printer() -> OctoPrinter:
    running = get_slicer_upload_service().machine_running()
    flags = OctoStateFlags(operational=running, ready=running, closedOrError=not running)
    return OctoPrinter(state=OctoState(text=_state_text(), flags=flags))


@router.get("/job", response_model=OctoJob, operation_id="octoprintJob",
            summary="OctoPrint job (always idle — jobs run from the UI)")
def job() -> OctoJob:
    return OctoJob(state=_state_text())


@router.get("/connection", response_model=OctoConnection, operation_id="octoprintConnection",
            summary="OctoPrint printer connection")
def connection() -> OctoConnection:
    return OctoConnection(current=OctoConnectionCurrent(state=_state_text()))


@router.post(
    "/files/local",
    response_model=OctoUploadResponse,
    status_code=201,
    operation_id="octoprintUploadFile",
    summary="Upload G-code from a slicer into nc_files/",
    description=(
        "OctoPrint's upload: 'path' is a folder under nc_files/, an existing file is "
        "overwritten. 'select' / 'print' load the file into LinuxCNC when it runs — "
        "it is never started from the network."
    ),
    responses={400: {"description": "Invalid file name."}, 415: {"description": "Not a G-code file."}},
)
def upload(
    request: Request,
    file: UploadFile = File(...),
    path: str = Form("", description="Folder under nc_files/ ('' = top level)."),
    select: bool = Form(False, description="Load the file into LinuxCNC."),
    print_: bool = Form(False, alias="print", description="Treated as 'select': never started remotely."),
) -> OctoUploadResponse:
    service = get_slicer_upload_service()
    try:
        stored = service.save(file.filename or "", path, file.file.read())
    except UnsupportedFileError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid file name: {exc}") from exc
    finally:
        file.file.close()

    loaded = service.load(stored) if (select or print_) else False
    base = str(request.base_url).rstrip("/")
    refs = OctoFileRefs(
        resource=f"{base}/api/files/local/{quote(stored)}",
        download=f"{base}/api/v1/programs/content/{quote(stored)}",
    )
    name = stored.rsplit("/", 1)[-1]
    return OctoUploadResponse(
        files=OctoUploadFiles(local=OctoUploadedFile(name=name, display=name, path=stored, refs=refs)),
        effectiveSelect=loaded,
    )


__all__ = ["router"]
