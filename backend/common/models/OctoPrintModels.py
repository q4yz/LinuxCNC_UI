"""Responses of the OctoPrint-compatible slicer API (``/api/version``,
``/api/files/local``, ...) — the subset OrcaSlicer / PrusaSlicer and
Cura's OctoPrint plugin use to send G-code over the network.

Field names follow OctoPrint's REST API (docs.octoprint.org/en/master/api),
not this project's style: the slicers parse them as-is.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

#: OctoPrint API / server version the slicers are told (the same Moonraker
#: reports — new enough for every slicer's version check).
OCTOPRINT_API_VERSION = "0.1"
OCTOPRINT_SERVER_VERSION = "1.5.0"


class OctoVersion(BaseModel):
    api: str = OCTOPRINT_API_VERSION
    server: str = OCTOPRINT_SERVER_VERSION
    #: PrusaSlicer / Orca only accept a host whose text starts with "OctoPrint".
    text: str = f"OctoPrint {OCTOPRINT_SERVER_VERSION} (LinuxCNC UI)"


class OctoServer(BaseModel):
    server: str = OCTOPRINT_SERVER_VERSION
    safemode: Optional[str] = None


class OctoLogin(BaseModel):
    name: str = "_api"
    active: bool = True
    user: bool = True
    admin: bool = True
    apikey: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)
    groups: List[str] = Field(default_factory=lambda: ["admins", "users"])


class OctoFeatures(BaseModel):
    sdSupport: bool = False
    temperatureGraph: bool = False


class OctoWebcam(BaseModel):
    webcamEnabled: bool = False
    streamUrl: str = ""
    flipH: bool = False
    flipV: bool = False
    rotate90: bool = False


class OctoSettings(BaseModel):
    plugins: Dict[str, None] = Field(default_factory=lambda: {"m33fio": None, "virtual_printer": None})
    feature: OctoFeatures = Field(default_factory=OctoFeatures)
    webcam: OctoWebcam = Field(default_factory=OctoWebcam)


class OctoExtruder(BaseModel):
    count: int = 1
    offsets: List[List[float]] = Field(default_factory=lambda: [[0.0, 0.0]])


class OctoPrinterProfile(BaseModel):
    id: str = "_default"
    name: str = "LinuxCNC"
    model: str = "LinuxCNC"
    color: str = "default"
    default: bool = True
    current: bool = True
    heatedBed: bool = True
    heatedChamber: bool = False
    extruder: OctoExtruder = Field(default_factory=OctoExtruder)


class OctoPrinterProfiles(BaseModel):
    profiles: Dict[str, OctoPrinterProfile] = Field(
        default_factory=lambda: {"_default": OctoPrinterProfile()}
    )


class OctoStateFlags(BaseModel):
    operational: bool
    ready: bool
    printing: bool = False
    paused: bool = False
    pausing: bool = False
    cancelling: bool = False
    error: bool = False
    closedOrError: bool


class OctoState(BaseModel):
    text: str
    flags: OctoStateFlags


class OctoPrinter(BaseModel):
    #: Temperatures stay empty: the slicers only send files, the UI shows the rest.
    temperature: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    state: OctoState


class OctoJobFile(BaseModel):
    name: Optional[str] = None
    origin: str = "local"
    size: Optional[int] = None
    date: Optional[int] = None


class OctoJobInfo(BaseModel):
    file: OctoJobFile = Field(default_factory=OctoJobFile)
    estimatedPrintTime: Optional[float] = None
    user: Optional[str] = None


class OctoProgress(BaseModel):
    completion: Optional[float] = None
    filepos: Optional[int] = None
    printTime: Optional[int] = None
    printTimeLeft: Optional[int] = None


class OctoJob(BaseModel):
    job: OctoJobInfo = Field(default_factory=OctoJobInfo)
    progress: OctoProgress = Field(default_factory=OctoProgress)
    state: str


class OctoConnectionCurrent(BaseModel):
    state: str
    port: str = "linuxcnc"
    baudrate: int = 0
    printerProfile: str = "_default"


class OctoConnection(BaseModel):
    current: OctoConnectionCurrent


class OctoFileRefs(BaseModel):
    resource: str
    download: str


class OctoUploadedFile(BaseModel):
    name: str
    display: str
    path: str
    origin: str = "local"
    refs: OctoFileRefs


class OctoUploadFiles(BaseModel):
    local: OctoUploadedFile


class OctoUploadResponse(BaseModel):
    files: OctoUploadFiles
    done: bool = True
    #: Whether the file was loaded into LinuxCNC (``select`` / ``print``).
    effectiveSelect: bool = False
    #: Always false: a network upload never starts the machine.
    effectivePrint: bool = False


__all__ = [
    "OctoConnection", "OctoConnectionCurrent", "OctoFileRefs", "OctoJob", "OctoLogin",
    "OctoPrinter", "OctoPrinterProfiles", "OctoServer", "OctoSettings", "OctoState",
    "OctoStateFlags", "OctoUploadFiles", "OctoUploadResponse", "OctoUploadedFile", "OctoVersion",
]
