"""``/api/v1/system/machine`` — LinuxCNC process lifecycle endpoints.

Thin HTTP wrapper around :class:`MachineLifecycleService`. These
endpoints live in the always-running system service so the machine
can be started, stopped and switched even while the machine backend
(or the machine itself) is down.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Query

from models.MachineLifecycleModels import (
    MachineDefaultRequest,
    MachineLogResponse,
    MachineStartRequest,
    MachineStartResponse,
    MachineStatusResponse,
    MachineSwitchRequest,
)

from services.MachineLifecycleService import (
    get_machine_lifecycle_service,
)

logger = logging.getLogger("backend.system.routers.machine_lifecycle")

router = APIRouter(prefix="/api/v1/system/machine", tags=["System: Machine Lifecycle"])


@router.get(
    "",
    summary="Get machine session status",
    description=(
        "Reports whether a LinuxCNC session is running (pgrep on "
        "linuxcnc/emc/milltask/linuxcncsvr), which machine is the "
        "persisted default, and whether its INI exists at "
        "machines/<default>/config/machine.ini."
    ),
    operation_id="getMachineSessionStatus",
    response_model=MachineStatusResponse,
)
def get_machine_status() -> MachineStatusResponse:
    return MachineStatusResponse(**get_machine_lifecycle_service().status())


@router.get(
    "/log",
    summary="Get the LinuxCNC console log tail",
    description=(
        "Returns the tail of every known LinuxCNC log, merged under "
        "labelled sections: this UI's own tee (logs/linuxcnc_console.log) "
        "plus LinuxCNC's own ~/linuxcnc_print.txt / ~/linuxcnc_debug.txt "
        "(where its launcher redirects once it isn't talking to an "
        "interactive terminal — true for every session we spawn). Lets "
        "an operator see why a session crashed or failed to start "
        "without shell access to the machine."
    ),
    operation_id="getMachineConsoleLog",
    response_model=MachineLogResponse,
)
def get_machine_log(
    lines: int = Query(200, ge=1, le=5000, description="Number of trailing lines to return."),
) -> MachineLogResponse:
    return MachineLogResponse(**get_machine_lifecycle_service().console_log(lines=lines))


@router.post(
    "/start",
    summary="Start the LinuxCNC session",
    description=(
        "Starts the LinuxCNC session. With a ``machine`` body that "
        "machine is persisted as the default and its "
        "machines/<machine>/config/machine.ini is launched; without "
        "one, the persisted default machine is started (404 when no "
        "default has been selected). Runs the console command as a "
        "detached process on the machine's display (DISPLAY=:0 unless "
        "inherited); console output is tee'd into "
        "logs/linuxcnc_console.log. Returns 409 when a session is "
        "already running and 404 when the machine's INI is missing. "
        "If the process exits immediately, the 400 response's detail "
        "includes the console log's tail; GET /log fetches it any time."
    ),
    operation_id="startMachineSession",
    response_model=MachineStartResponse,
    responses={
        409: {"description": "LinuxCNC is already running."},
        404: {"description": "No default machine selected, or the machine's config/machine.ini is missing."},
        400: {"description": "The process failed to start or exited immediately."},
    },
)
def start_machine(
    payload: MachineStartRequest = Body(default=MachineStartRequest()),
) -> MachineStartResponse:
    return MachineStartResponse(
        **get_machine_lifecycle_service().start(machine=payload.machine)
    )


@router.post(
    "/default",
    summary="Set the default machine",
    description=(
        "Persists the default machine (\"Select as main\") without "
        "starting anything. Generic \"Start machine\" actions launch "
        "this machine's machines/<default>/config/machine.ini."
    ),
    operation_id="setDefaultMachine",
    response_model=MachineStatusResponse,
    responses={
        404: {"description": "The machine's config/machine.ini is missing."},
        400: {"description": "Invalid machine path."},
    },
)
def set_default_machine(payload: MachineDefaultRequest) -> MachineStatusResponse:
    service = get_machine_lifecycle_service()
    service.set_default_machine(payload.machine)
    return MachineStatusResponse(**service.status())


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
        "deploy a generated machine's templates into machine_config/active "
        "(see POST /modules/machineconfig/machines/generate to produce them "
        "first), and start the new machine."
    ),
    operation_id="switchMachine",
    response_model=MachineStartResponse,
    responses={
        404: {"description": "Machine or generated INI not found."},
        400: {"description": "Invalid machine path or the machine failed to start."},
    },
)
def switch_machine(
    payload: MachineSwitchRequest = Body(default=MachineSwitchRequest()),
) -> MachineStartResponse:
    result = get_machine_lifecycle_service().switch(
        machine=payload.machine,
        start_machine=payload.start,
    )
    return MachineStartResponse(**result)
