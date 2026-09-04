"""Shared Pydantic model for the per-module "macro button" feature.

The frontend's shared ``MacroButton`` primitive (see
``frontend/src/ui/MacroButton.vue``) renders an operator-configurable
button that runs a macro on click. Configuration is persisted per
module against the canonical :class:`core.settings_store.SettingsStore`
under the ``macroButtons`` key.

Each owning module (``axis`` / ``camera`` / future modules) declares
its own list of ``slot`` ids (``dro.x`` / ``dro.y`` / ``dro.z`` /
``camera.bottom`` / ...) and stores a list of
:class:`MacroButtonDescriptor` rows keyed by the host module's
``settings.json``. The frontend normalises the wire shape to a
``macroButtons`` array (camelCase); the schema's field names use
snake_case to match the rest of the backend Pydantic surface.

A descriptor is only rendered when ``enabled`` is true and
``macro_name`` is non-empty — the frontend treats missing / empty
values as "hide this button". A host that does not yet ship a slot
just keeps an empty list; defaults land as ``[]`` on first boot
via the Pydantic :func:`Field(default_factory=list)` contract.

The kind taxonomy matches ``backend.services.MacroService.MacroKind``
(``"macro"`` / ``"ngc"``). ``mcode`` is intentionally excluded: an
operator who needs an M-code call wraps it in a ``.macro`` instead.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# Whitelisted dispatch kinds. Matches
# ``backend.services.MacroService.MacroKind`` — kept as a literal here
# rather than importing from the service to avoid a
# ``services → models`` import cycle. Mirrors the
# ``MACRO_KIND`` constant the frontend exports from
# ``frontend/src/modules/macros/store.ts``.
MacroButtonKind = Literal["macro", "ngc"]


class MacroButtonDescriptor(BaseModel):
    """One configurable "custom macro button" on a host surface.

    Attributes:
        slot: Stable identifier the host declares (e.g.
            ``"dro.x"`` / ``"dro.y"`` / ``"dro.z"`` / ``"camera.bottom"``).
            Frontend and backend agree on a string-id convention so a
            future host only needs to extend the slot id list.
        enabled: Operator toggle. A disabled row is hidden from the
            host surface but kept in the persisted payload so the
            operator can re-enable it without re-typing the macro.
        name: Human-readable label rendered inside the button. May
            be empty while the operator is still configuring the
            row; the frontend renders nothing until ``name`` and
            ``macro_name`` are both non-empty.
        icon: Free-text icon field. The frontend treats a value
            matching a name in ``frontend/src/ui/Icon.vue`` as an
            SVG glyph and anything else (emoji, unicode) as a
            literal span. Empty falls back to the label only.
        macro_kind: ``"macro"`` for ``.macro`` files (parsed + MDI
            dispatch on click) or ``"ngc"`` for ``.ngc`` files
            (delegated to the backend's
            ``POST /api/v1/modules/macros/{name}/start?kind=ngc``
            endpoint).
        macro_name: Macro name (without extension) the click handler
            dispatches. Empty → host surface renders no button.
    """

    slot: str = Field(
        min_length=1,
        description="Stable slot id the host declares (e.g. 'dro.x').",
    )
    enabled: bool = Field(
        default=False,
        description="Operator toggle. Disabled rows are persisted but hidden.",
    )
    name: str = Field(
        default="",
        description="Human-readable label rendered inside the button.",
    )
    icon: str = Field(
        default="",
        description=(
            "Free-text icon: an <Icon> name (matches a glyph) or an "
            "emoji / unicode literal."
        ),
    )
    macro_kind: MacroButtonKind = Field(
        default="macro",
        description=(
            "Dispatch kind. 'macro' uses the MDI block parser; "
            "'ngc' delegates to /macros/{name}/start?kind=ngc."
        ),
    )
    macro_name: str = Field(
        default="",
        description="Macro name (without extension) the click handler dispatches.",
    )


__all__ = ["MacroButtonDescriptor", "MacroButtonKind"]