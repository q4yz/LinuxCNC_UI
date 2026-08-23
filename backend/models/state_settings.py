"""Pydantic defaults model for the state module settings.

The schema documents the canonical shape the
:class:`core.settings_store.SettingsStore` will serve on
``GET /api/v1/modules/machine_state/settings``. New keys can be
added in later releases without breaking existing deployments —
the store merges the defaults underneath the persisted payload so
a missing key is filled in from this schema's defaults on every
read.

The state module has **no user-tunable settings today** — the
HTTP surface is purely a state / mode / MDI dispatcher. The
schema is intentionally minimal (a single ``confirm_mode_change``
toggle) but present so the canonical four settings endpoints
expose a non-empty payload from first boot. Future knobs
(history persistence, default mode on boot, …) land as new
fields on this model without breaking the contract.

Field semantics:

* ``confirm_mode_change`` — When ``True`` the dashboard shows a
  confirmation dialog before switching between ``MANUAL``,
  ``MDI`` and ``AUTO``. ``False`` (default) lets the operator
  switch modes with a single click. The flag is consulted
  read-only by the backend — the frontend owns the dialog
  surface.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class StateSettings(BaseModel):
    """User-tunable knobs for the state module.

    Attributes:
        confirm_mode_change: When ``True`` the dashboard shows a
            confirmation dialog before switching between MANUAL,
            MDI and AUTO. Default ``False``.
    """

    confirm_mode_change: bool = Field(
        default=False,
        description=(
            "When True, the dashboard shows a confirmation "
            "dialog before switching between MANUAL, MDI and "
            "AUTO. Default False."
        ),
    )


__all__ = ["StateSettings"]