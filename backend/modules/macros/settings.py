"""Pydantic defaults model for the macros module settings.

The schema documents the canonical shape the
:class:`core.settings_store.SettingsStore` will serve on
``GET /api/v1/modules/macros/settings``. New keys can be added in
later releases without breaking existing deployments — the store
merges the defaults underneath the persisted payload so a missing
key is filled in from this schema's defaults on every read.

Field semantics:

* ``show_dangerous_macros`` — When ``True`` the universal editor
  surfaces macro files whose body contains a structurally risky
  token (``G0``, ``M0``, hard-coded ``S`` spindle speeds, …)
  without an explicit confirmation banner. When ``False``
  (default) the editor hides them behind an opt-in toggle so a
  casual operator never trips a hard-coded ``S24000`` or an
  unsignalled ``M0``. The flag is consulted read-only by the
  backend — the frontend owns the editor surface.

The Phase 3a macros module has no dedicated settings UI — the
``settings_panel`` flag in :mod:`backend.modules.macros.module`
stays ``False`` until the frontend gains a tab for it. The
SettingsStore endpoints still expose this schema so the four
canonical settings endpoints return a non-empty payload from
first boot (the registry contract).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class MacrosSettings(BaseModel):
    """User-tunable knobs for the macros module.

    Attributes:
        show_dangerous_macros: When ``True`` the universal editor
            surfaces structurally risky macro files without a
            confirmation banner. ``False`` (default) hides them
            behind an opt-in toggle.
    """

    show_dangerous_macros: bool = Field(
        default=False,
        description=(
            "When True, the universal editor surfaces structurally "
            "risky macro files without a confirmation banner. "
            "Default False hides them behind an opt-in toggle."
        ),
    )


__all__ = ["MacrosSettings"]