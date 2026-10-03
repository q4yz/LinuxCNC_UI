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
