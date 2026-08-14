"""Pydantic defaults model for the tools module settings.

The schema documents the canonical shape the
:class:`core.settings_store.SettingsStore` will serve on
``GET /api/v1/modules/tools/settings``. New keys can be added in
later releases without breaking existing deployments — the store
merges the defaults underneath the persisted payload so a missing
key is filled in from this schema's defaults on every read.

Field semantics:

* ``confirm_spindle_start`` — When ``True`` the dashboard shows
  a confirmation dialog before dispatching ``M3`` / ``M4``.
  ``False`` (default) lets the operator fire the spindle with a
  single click. The flag is consulted read-only by the backend
  — the frontend owns the dialog surface.
* ``max_spindle_rpm`` — Hard upper bound the dashboard renders
  on the spindle target-RPM input and the router enforces on
  ``POST /spindle``. ``12 000`` is the historical default that
  predates the typed settings schema; bump it via PUT
  ``/api/v1/modules/tools/settings`` if your VFD accepts a
  higher ceiling. Bounded to ``[0, 200_000]`` so a misconfigured
  value cannot be dispatched as ``M3 S{absurd}``.

The Phase 3a tools module has no dedicated settings UI — the
``settings_panel`` flag in :mod:`backend.modules.tools.module`
stays ``False`` until the frontend gains a tab for it. The
SettingsStore endpoints still expose this schema so the four
canonical settings endpoints return a non-empty payload from
first boot (the registry contract).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ToolsSettings(BaseModel):
    """User-tunable knobs for the tools module.

    Attributes:
        confirm_spindle_start: When ``True`` the dashboard shows
            a confirmation dialog before dispatching ``M3`` /
            ``M4``. Default ``False``.
        max_spindle_rpm: Hard upper bound on the spindle
            target-RPM input. Range 0–200 000.
    """

    confirm_spindle_start: bool = Field(
        default=False,
        description=(
            "When True, the dashboard shows a confirmation "
            "dialog before dispatching M3 / M4. Default False."
        ),
    )
    max_spindle_rpm: int = Field(
        default=12000,
        ge=0,
        le=200_000,
        description=(
            "Hard upper bound the dashboard renders on the "
            "spindle target-RPM input and the router enforces "
            "on POST /spindle."
        ),
    )


__all__ = ["ToolsSettings"]