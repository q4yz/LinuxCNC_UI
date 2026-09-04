from pydantic import BaseModel, Field


class ToolCommandResponse(BaseModel):
    status: str = Field(default="success")
    command: str = Field(...)
    tool_id: str = Field(...)