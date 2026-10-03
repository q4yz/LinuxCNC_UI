from typing import Any, Dict

from pydantic import BaseModel, Field


class UiSettingsListResponse(BaseModel):
    """Every stored UI setting. Keys that were never written are absent —
    the frontend falls back to each setting's own default."""
    values: Dict[str, Any] = Field(default_factory=dict, description="Stored settings keyed by setting key.")


class UiSettingValue(BaseModel):
    """Body of ``PUT /api/v1/settings/{key}``."""
    value: Any = Field(..., description="Any JSON value; the frontend setting type validates it.")


class UiSettingResponse(BaseModel):
    """One stored setting. On a write this echoes what was persisted —
    the frontend treats it as the confirmation."""
    key: str
    value: Any = None
