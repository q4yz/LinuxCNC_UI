"""The ACE tool change's contract between the NGC, HAL and the backend.

``M640 P<slot>`` (``machine_config/m_codes/ace_change.ngc``) parks, cuts
and then asks the machine backend (``services.filament.AceService``) for
the filament change over HAL — LinuxCNC's motion I/O, netted to the
``webgui`` component in ``webgui_connections.hal``:

    M68 E<SLOT_AOUT> Q<slot>   motion.analog-out-NN  -> webgui.ace-slot     (-1: unload only)
    M64 P<REQUEST_DOUT>        motion.digital-out-NN -> webgui.ace-request  (rising edge: go)
    M66 P<DONE_DIN> L3         webgui.ace-done       -> motion.digital-in-NN
                               webgui.ace-error      -> motion.digital-in-NN (with done: it failed)
    M65 P<REQUEST_DOUT>        request low: the backend clears done / error

``webgui.ace-current`` is the loaded slot (-1 none, -2 unknown) for the
NGC's "already loaded" check. motmod's default 4 digital / 4 analog
channels are enough; the ACE takes the top ones.
"""
from __future__ import annotations

REQUEST_DOUT = 3
SLOT_AOUT = 3
DONE_DIN = 3
ERROR_DIN = 2

PIN_REQUEST = "ace-request"
PIN_SLOT = "ace-slot"
PIN_DONE = "ace-done"
PIN_ERROR = "ace-error"
PIN_CURRENT = "ace-current"

NO_SLOT = -1
UNKNOWN_SLOT = -2

M_CODE = "M640"
REMAP = f"REMAP={M_CODE} modalgroup=10 argspec=P ngc=ace_change"

__all__ = [
    "DONE_DIN", "ERROR_DIN", "M_CODE", "NO_SLOT", "PIN_CURRENT", "PIN_DONE", "PIN_ERROR", "PIN_REQUEST", "PIN_SLOT",
    "REMAP", "REQUEST_DOUT", "SLOT_AOUT", "UNKNOWN_SLOT",
]
