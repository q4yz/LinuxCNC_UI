"""A heater/extruder tool's id -> its `machine.ini` PID section name.

One name, two independent consumers that must never drift apart:
`HeaterHalMapper` writes `setp PID-<id>.KP [<SECTION>]PID_KP` into
`machine.hal`, and `ini_template_generator` writes the matching
`[<SECTION>]` block into `machine.ini` — if the two ever compute this
differently, the HAL loads fine but every gain resolves to an
undefined ini variable, silently zeroing the loop.

Uses the tool's own id verbatim (uppercased), not a LinuxCNC-style
`EXT0`/`BED` abbreviation: `heater_bed` -> `HEATER_BED`,
`heater_extruder` -> `HEATER_EXTRUDER`. Two consequences worth being
explicit about:

* It reads as "temperature control", not "extruder-specific" — the
  same shape names a heated bed, a hot end, or a `heater_generic`
  chamber heater alike.
* It is unique by construction for multiple extruders/heaters,
  because `tools[].id` already has to be (every heater-shaped id is
  distinct — see `heater.md` § 2's `E_HEATER_ID_COLLISION`). A second
  extruder (`heater_extruder_test`) gets its own section
  (`HEATER_EXTRUDER_TEST`) for free, with no separate numbering
  scheme to keep in sync.
"""

from __future__ import annotations


def heater_ini_section(heater_id: str) -> str:
    """`"heater_bed"` -> `"HEATER_BED"`."""
    return heater_id.upper()


__all__ = ["heater_ini_section"]
