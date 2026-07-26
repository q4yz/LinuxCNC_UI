"""Pydantic defaults for the machineconfig module.

The four keys are the only knobs the operator needs to tune:

* ``default_compiler_id`` — preselects a compiler in the frontend
  dropdown so a fresh install lands on the canonical Klipper →
  LinuxCNC translator rather than ``None``.
* ``confirm_flash_default`` — initial state of the "Confirm Flash"
  toggle on the deploy panel. The UI lets the operator change it
  per-deploy, but the setting exists so a deployment can be
  pre-flagged as "flash required" by an admin profile.
* ``require_confirm_flash`` — when ``True`` (default), the deploy
  endpoint rejects the request unless the operator ticks the box.
  Useful for environments where Remora boards are in the loop and
  a missing flash acknowledgement could brick a remote machine.
* ``auto_readonly_after_stage`` — when ``True`` (default), the
  compile step marks the staged artifacts read-only. Set to
  ``False`` for lab setups where the operator routinely hand-edits
  the staged INI before deploying.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MachineConfigSettings(BaseModel):
    """User-tunable knobs for the machineconfig module."""

    default_compiler_id: str = Field(
        default="klipper-to-linuxcnc",
        description=(
            "Compiler id selected by default in the frontend compiler "
            "dropdown. Must match a registered Compiler.id."
        ),
    )
    confirm_flash_default: bool = Field(
        default=False,
        description=(
            "Initial state of the 'Confirm Flash' toggle on the "
            "deployment panel."
        ),
    )
    require_confirm_flash: bool = Field(
        default=True,
        description=(
            "When True, the deploy endpoint rejects requests unless the "
            "operator supplies confirm_flash=true. Useful when the "
            "deployment target is a remote controller such as Remora."
        ),
    )
    auto_readonly_after_stage: bool = Field(
        default=True,
        description=(
            "When True, the compile step marks every staged artifact "
            "read-only so a typo on the Active dashboard cannot silently "
            "diverge from the staged payload."
        ),
    )


__all__ = ["MachineConfigSettings"]