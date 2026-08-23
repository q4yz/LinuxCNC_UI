"""Reusable field-masking primitives for Pydantic response assembly.

When a single response model serves multiple "tiers" of consumers
(static config vs. dynamic state vs. per-thread snapshots), the
mapper layer can use :func:`include_if` to populate a field only
when the caller asked for that tier. Combined with the route's
``response_model_exclude_none=True``, the field is dropped from the
JSON payload when it wasn't requested.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Iterable, Optional, Union


class ResponseTier(str, Enum):
    """Available response projection modes."""
    STATIC = "static"
    BASE = "base"
    ALL = "all"

def include_if(value: Any, current_mode: Union[ResponseTier, str],target_modes: Iterable[Union[ResponseTier, str]]) -> Optional[Any]:
    if current_mode in target_modes or ResponseTier.ALL in target_modes or current_mode == ResponseTier.ALL:
        return value
    return None

def include_base(value: Any, current_mode: Union[ResponseTier, str]) -> Optional[Any]:
    """Shorthand wrapper to include a field ONLY in the 1Hz Base thread."""
    return include_if(value, current_mode, {ResponseTier.BASE})

def include_static(value: Any, current_mode: Union[ResponseTier, str]) -> Optional[Any]:
    """Shorthand wrapper to include a field ONLY in the Static config."""
    return include_if(value, current_mode, {ResponseTier.STATIC})

def include_both(value: Any, current_mode: Union[ResponseTier, str]) -> Optional[Any]:
    """Shorthand wrapper to include a field in BOTH Base and Static payloads."""
    return include_if(value, current_mode, {ResponseTier.BASE, ResponseTier.STATIC})
