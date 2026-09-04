"""``/api/v1/system/machine`` — LinuxCNC process lifecycle endpoints.

Thin HTTP wrapper around :class:`MachineLifecycleService`. These
endpoints live in the always-running system service so the machine
can be started, stopped and switched even while the machine backend
(or the machine itself) is down.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

from services.MachineLifecycleService import (
    get_machine_lifecycle_service,
)

logger = logging.getLogger("backend.system.routers.machine_lifecycle")

router = APIRouter(prefix="/api/v1/system/machine", tags=["System: Machine Lifecycle"])


class MachineStatusResponse(BaseModel):
    """Live state of the LinuxCNC session and the generated INI."""

    running: bool = Field(..., description="Whether a LinuxCNC session process is alive.")
    pids: List[int] = Field(..., description="Pids of the detected LinuxCNC processes.")
    machine_name: Optional[str] = Field(
        None, description="Machine name from the active INI, if deployed."
    )
    ini_path: Optional[str] = Field(
        None, description="Path of the generated INI under machine_config/active."
    )
    ini_exists: bool = Field(..., description="Whether a generated INI exists.")


class MachineStartResponse(MachineStatusResponse):
    started_pid: Optional[int] = Field(
        None, description="Pid of the launched LinuxCNC process."
    )


class MachineSwitchRequest(BaseModel):
    profile: Optional[str] = Field(
        None,
        description=(
            "Optional profile path under machine_config/profiles to compile "
            "before deploying (e.g. 'starter.cfg'). When omitted, the staged "
            "artifacts in machine_config/ready_for_deploy are deployed."
        ),
    )
    start: bool = Field(
        True,
        description="Start the machine session after deploying the new config.",
    )


@router.get(
    "",
    summary="Get machine session status",
    description=(
        "Reports whether a LinuxCNC session is running (pgrep on "
        "linuxcnc/emc/milltask/linuxcncsvr), which machine is active, and "
        "whether a generated INI exists under machine_config/active."
    ),
    operation_id="getMachineSessionStatus",
    response_model=MachineStatusResponse,
)
def get_machine_status() -> MachineStatusResponse:
    return MachineStatusResponse(**get_machine_lifecycle_service().status())


@router.post(
    "/start",
    summary="Start the LinuxCNC session",
    description=(
        "Runs the console command `linuxcnc <machine_config/active/machine.ini>` "
        "as a detached console process on the machine's display (DISPLAY=:0 "
        "unless inherited). Console output is tee'd into "
        "logs/linuxcnc_console.log. Returns 409 when a session is already "
        "running and 404 when no generated INI has been deployed."
    ),
    operation_id="startMachineSession",
    response_model=MachineStartResponse,
    responses={
        409: {"description": "LinuxCNC is already running."},
        404: {"description": "No generated INI in machine_config/active, or the linuxcnc executable is missing."},
        400: {"description": "The process failed to start or exited immediately."},
    },
)
def start_machine() -> MachineStartResponse:
    return MachineStartResponse(**get_machine_lifecycle_service().start())


@router.post(
    "/stop",
    summary="Stop the LinuxCNC session",
    description=(
        "Stops the running LinuxCNC session: SIGINT first (like Ctrl+C in "
        "the console), escalating to SIGTERM and finally SIGKILL after the "
        "grace period. Idempotent — stopping a stopped machine succeeds."
    ),
    operation_id="stopMachineSession",
    response_model=MachineStatusResponse,
)
def stop_machine() -> MachineStatusResponse:
    return MachineStatusResponse(**get_machine_lifecycle_service().stop())


@router.post(
    "/switch",
    summary="Switch the active machine",
    description=(
        "Switch machines in one action: stop the running session, optionally "
        "compile the given profile (default compiler), deploy the staged "
        "artifacts into machine_config/active, and start the new machine."
    ),
    operation_id="switchMachine",
    response_model=MachineStartResponse,
    responses={
        404: {"description": "Profile or generated INI not found."},
        400: {"description": "Staging area empty or the machine failed to start."},
    },
)
def switch_machine(
    payload: MachineSwitchRequest = Body(default=MachineSwitchRequest()),
) -> MachineStartResponse:
    result = get_machine_lifecycle_service().switch(
        profile=payload.profile,
        start_machine=payload.start,
    )
    return MachineStartResponse(**result)
