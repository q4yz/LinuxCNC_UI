"""Response / payload models of the macros domain (both backends)."""
from typing import List

from pydantic import BaseModel, Field

from storage.MacroStorage import MacroKind

__all__ = ["MacroKind", "MacroListItem", "MacroListResponse", "MacroWriteResponse", "MacroContentPayload", "MacroContentResponse"]


class MacroListItem(BaseModel):
    name: str = Field(..., description="File name without extension.")
    kind: str = Field(..., description="One of macro / ngc / mcode.")
    size_bytes: int = Field(..., description="On-disk byte size.")


class MacroListResponse(BaseModel):
    macros: List[MacroListItem] = Field(
        default_factory=list,
        description="Macro entries of the requested kind, sorted by name.",
    )


class MacroWriteResponse(BaseModel):
    name: str = Field(..., description="File name (no extension).")
    kind: str = Field(..., description="One of macro / ngc / mcode.")
    size: int = Field(..., description="Size of the persisted payload in bytes.")


class MacroContentPayload(BaseModel):
    content: str = Field(..., description="Raw macro payload (UTF-8 text).")


class MacroContentResponse(BaseModel):
    name: str = Field(..., description="File name (no extension).")
    kind: str = Field(..., description="One of macro / ngc / mcode.")
    content: str = Field(..., description="Raw text content of the file.")
    size_bytes: int = Field(..., description="On-disk byte size.")
