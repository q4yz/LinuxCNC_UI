from pydantic import BaseModel, Field


class StatusResponse(BaseModel):
    """Generic response model for endpoints that return a status string."""

    status: str = Field(
        ...,
        description="Outcome reported by the hardware layer (e.g., 'success')",
    )


class ParseResponse(BaseModel):
    """Response model for the Klipper-to-LinuxCNC parser trigger."""

    status: str = Field(..., description="Outcome of the parser trigger")
    message: str = Field(..., description="Human-readable status message")


class LoadProgramRequest(BaseModel):
    filename: str


class ProgramProgressResponse(BaseModel):
    """Progress snapshot for the active G-code program.

    Returned by ``GET /api/v1/modules/program/progress`` so the dashboard
    can poll once a second without saturating NML. ``total_lines``
    comes from a backend-side line-count cache populated when the
    file is loaded; ``current_line`` and ``motion_line`` come
    straight from ``linuxcnc.stat``. ``interp_state`` mirrors the
    raw integer so the widget can decide whether to keep polling.
    """

    current_line: int = Field(
        ...,
        ge=0,
        description=(
            "Line the RS274NGC interpreter is currently reading. "
            "Mirrors ``stat.current_line``."
        ),
    )
    motion_line: int = Field(
        ...,
        ge=0,
        description=(
            "Source line motion is currently executing. Mirrors "
            "``stat.motion_line``; ``0`` when the interpreter is idle."
        ),
    )
    total_lines: int = Field(
        ...,
        ge=0,
        description=(
            "Total line count of the loaded G-code file, populated "
            "from a backend-side cache at ``program_open`` time. "
            "``0`` when no file is loaded or the file was unreadable."
        ),
    )
    file: str = Field(
        ...,
        description=(
            "Absolute path of the loaded G-code file (``stat.file``) "
            "or empty string when nothing is loaded."
        ),
    )
    interp_state: int = Field(
        ...,
        description=(
            "Current ``linuxcnc.INTERP_*`` state. ``1`` IDLE, "
            "``2`` READING, ``3`` PAUSED, ``4`` WAITING."
        ),
    )
