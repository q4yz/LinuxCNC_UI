"""``[ace]`` -> `webgui_connections.hal`: the tool change's handshake
between ``ace_change.ngc`` (motion I/O) and the machine backend
(``webgui.ace-*``), see ``core.ace_contract``."""
from __future__ import annotations

from core import ace_contract as c


class AceWebguiMapper:
    @staticmethod
    def to_lines() -> list[str]:
        return [
            "# ACE Pro tool change (M640): NGC <-> machine backend",
            f"net ace-request motion.digital-out-{c.REQUEST_DOUT:02d} => webgui.{c.PIN_REQUEST}",
            f"net ace-slot motion.analog-out-{c.SLOT_AOUT:02d} => webgui.{c.PIN_SLOT}",
            f"net ace-done webgui.{c.PIN_DONE} => motion.digital-in-{c.DONE_DIN:02d}",
            f"net ace-error webgui.{c.PIN_ERROR} => motion.digital-in-{c.ERROR_DIN:02d}",
            "",
        ]


__all__ = ["AceWebguiMapper"]
