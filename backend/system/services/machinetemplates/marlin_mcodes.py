"""Marlin heater / fan M-codes for LinuxCNC (`.agent/component/gcode_upload.md` § 3).

LinuxCNC does not know ``M104`` (hotend), ``M109`` (hotend, wait),
``M140`` / ``M190`` (bed), ``M106`` / ``M107`` (fan). A machine with a
heater or a part fan gets them as INI ``REMAP`` lines; everything else is
static and shared by every machine, in ``machine_config/m_codes/``
(``USER_M_PATH`` and ``SUBROUTINE_PATH``):

* ``m104.ngc`` ... ``m107.ngc`` — the remap subroutines;
* ``M180`` / ``M181`` / ``M182`` — helper user M-codes they call (set a
  heater target / set and wait / set a fan), reading the running
  machine's ``hardware.json``.

Only this machine's ``REMAP`` lines differ: a machine without a heater
or part fan (a mill, a laser without a fan) gets none, so ``M104`` /
``M106`` stay unknown there, as before.

The remapped codes take ``P`` / ``Q``: an ``S`` word would also set the
spindle speed. Uploaded files are converted (``core.gcode_converter``:
``M104 S200 T1`` -> ``M104 P200 Q1``); type ``P`` in MDI and macros.
"""
from __future__ import annotations

from typing import Any

from mappers.machineconfig import PinStringMapper


def _has_heater(payload: dict[str, Any], kind: str) -> bool:
    return any(isinstance(t, dict) and t.get("type") == kind for t in payload.get("tools") or [])


def _has_part_fan(payload: dict[str, Any]) -> bool:
    """A commandable part fan. A heater's placeholder fan shares the
    heater's own pin (``duplicate_pin_overrides``) and does not count —
    the helper never drives it either."""
    shared = {str(p) for p in payload.get("duplicate_pin_overrides") or []}
    for fan in payload.get("fans") or []:
        if not isinstance(fan, dict) or fan.get("kind", "part") != "part":
            continue
        try:
            if PinStringMapper.from_string(str(fan.get("pin") or "")).qualified not in shared:
                return True
        except ValueError:
            continue
    return False


def marlin_remaps(payload: dict[str, Any]) -> list[str]:
    """``[RS274NGC] REMAP=`` lines for ``payload`` (empty: no heater, no fan)."""
    remaps: list[str] = []
    if _has_heater(payload, "extruder"):
        remaps += ["REMAP=M104 modalgroup=10 argspec=pq ngc=m104", "REMAP=M109 modalgroup=10 argspec=pq ngc=m109"]
    if _has_heater(payload, "heated_bed"):
        remaps += ["REMAP=M140 modalgroup=10 argspec=p ngc=m140", "REMAP=M190 modalgroup=10 argspec=p ngc=m190"]
    if _has_part_fan(payload):
        remaps += ["REMAP=M106 modalgroup=10 argspec=pq ngc=m106", "REMAP=M107 modalgroup=10 argspec=q ngc=m107"]
    return remaps


__all__ = ["marlin_remaps"]
