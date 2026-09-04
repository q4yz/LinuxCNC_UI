"""Pydantic defaults for the machineconfig module.

No operator-tunable knobs today. The four flags that used to live
here (``default_compiler_id``, ``confirm_flash_default``,
``require_confirm_flash``, ``auto_readonly_after_stage``) were all
specific to the deprecated pluggable-compiler / Remora-flash
pipeline (see ``.agent/HANDOFF.md``) and were removed along with it.
The model still exists (rather than dropping the module entirely)
because every module id needs a settings class for the canonical
``/api/v1/modules/<id>/settings`` surface — a future template-system
knob (e.g. a default profile, or a deploy confirmation toggle) has
somewhere to land without re-plumbing the router.
"""

from __future__ import annotations

from pydantic import BaseModel


class MachineConfigSettings(BaseModel):
    """User-tunable knobs for the machineconfig module (currently none)."""


__all__ = ["MachineConfigSettings"]
