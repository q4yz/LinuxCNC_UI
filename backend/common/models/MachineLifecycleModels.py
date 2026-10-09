"""Request / response models of ``/api/v1/system/machine`` (``routers/machine_lifecycle.py``)."""
from typing import List, Optional
from pydantic import BaseModel, Field


class MachineStatusResponse(BaseModel):
    """Live state of the LinuxCNC session and the default machine."""

    running: bool = Field(..., description="Whether a LinuxCNC session process is alive.")
    pids: List[int] = Field(..., description="Pids of the detected LinuxCNC processes.")
    machine_name: Optional[str] = Field(
        None,
        description="Deprecated alias of ``default_machine`` (kept until the generated client is regenerated).",
    )
    default_machine: Optional[str] = Field(
        None,
        description="Machine folder (under machine_config/machines) selected as the default.",
    )
    ini_path: Optional[str] = Field(
        None,
        description="Path of the default machine's INI (machines/<default>/config/machine.ini), if it exists.",
    )
    ini_exists: bool = Field(..., description="Whether the default machine's INI exists.")


class MachineStartResponse(MachineStatusResponse):
    started_pid: Optional[int] = Field(
        None, description="Pid of the launched LinuxCNC process."
    )


class MachineStartRequest(BaseModel):
    """Optional body for ``POST /start``."""

    machine: Optional[str] = Field(
        None,
        description=(
            "Machine folder under machine_config/machines. When given, "
            "it is persisted as the default (start implies main) and "
            "its config/machine.ini is launched. When omitted, the "
            "persisted default machine is started."
        ),
    )


class MachineDefaultRequest(BaseModel):
    """Body for ``POST /default`` — select the default machine."""

    machine: str = Field(
        ...,
        description=(
            "Machine folder under machine_config/machines. Persisted as "
            "the default without starting anything; the folder must "
            "contain config/machine.ini."
        ),
    )


class MachineLogResponse(BaseModel):
    """Merged tail of every known LinuxCNC log."""

    path: str = Field(..., description="Absolute path of this UI's own console-log tee.")
    exists: bool = Field(..., description="Whether at least one of the known log sources exists yet.")
    log: str = Field(
        ...,
        description=(
            "Merged, labelled tail of every log source that exists (this UI's "
            "tee plus LinuxCNC's own ~/linuxcnc_print.txt / ~/linuxcnc_debug.txt), "
            "most recent lines last within each section. Empty when none exist yet."
        ),
    )


class MachineSwitchRequest(BaseModel):
    machine: Optional[str] = Field(
        None,
        description=(
            "Optional path under machine_config/machines to a generated "
            "machine (e.g. 'PrintNC' or 'PrintNC/configs') — generate it "
            "first with POST /modules/machineconfig/machines/generate. "
            "When given, that machine's templates are deployed into "
            "machine_config/active before starting; when omitted, the "
            "machine currently in active/ is simply restarted."
        ),
    )
    start: bool = Field(
        True,
        description="Start the machine session after deploying the new config.",
    )
