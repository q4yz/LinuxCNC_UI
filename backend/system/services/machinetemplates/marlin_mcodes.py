"""Marlin heater / fan M-codes for LinuxCNC (`.agent/component/gcode_upload.md` § 3).

LinuxCNC does not know ``M104`` (hotend), ``M109`` (hotend, wait),
``M140`` / ``M190`` (bed), ``M106`` / ``M107`` (fan). It cannot REMAP
them either: M100-M199 are reserved for *user M-code programs* — an
executable named exactly like the code in ``[RS274NGC] USER_M_PATH``
(``machine_config/m_codes/``); a ``REMAP=M104`` line is silently
ignored ("Unknown m code used: M104"). So the six codes are files there,
copies of the helper script (``M180`` ... ``M183``) that does what its
name says, reading the running machine's ``hardware.json`` — shared by
every machine, nothing is generated per machine. On a machine without a
heater or fan the script fails with "this machine has no ...".

A user M-code only gets ``P`` and ``Q``: an uploaded file is converted
(``core.gcode_converter``: ``M104 S200 T1`` -> ``M104 P200 Q1``) and so
is a Marlin code typed in MDI (``StateService.mdi``).
"""
from __future__ import annotations

import re

#: Marlin's codes, user M-code programs in ``machine_config/m_codes/``.
MARLIN_USER_MCODES = ("M104", "M106", "M107", "M109", "M140", "M190")

#: A REMAP LinuxCNC ignores: M100-M199 are user M-code programs.
USER_MCODE_REMAP = re.compile(r"^\s*REMAP\s*=\s*M1\d\d\b", re.IGNORECASE)


__all__ = ["MARLIN_USER_MCODES", "USER_MCODE_REMAP"]
