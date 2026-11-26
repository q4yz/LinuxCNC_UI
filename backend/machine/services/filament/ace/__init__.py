"""The Anycubic ACE Pro (gen 1) protocol: framing, a client, a simulator.

Plain Python with no LinuxCNC or backend imports, so it can be tested
without hardware and lifted out as its own package later. Written from
the public-domain protocol description (ACEResearch, CC0); the GPL
drivers (ValgACE, DuckACE, ACEPROSV08) were read for behaviour only.

* :mod:`.frame`  — ``FF AA | len | JSON | CRC-16/MCRF4XX | FE`` frames
* :mod:`.models` — typed ``get_info`` / ``get_status`` / filament info
* :mod:`.client` — requests, one in flight, keep-alive, reconnects
* :mod:`.transport` — the USB serial port (pyserial)
* :mod:`.sim`    — a simulated ACE for tests and UI work
"""
from .client import AceClient, AceError, AceTimeout, AceUnavailable
from .frame import FrameDecoder, FrameError, crc16_mcrf4xx, encode_frame
from .models import AceInfo, AceStatus, DryerStatus, FilamentInfo, SlotStatus

__all__ = [
    "AceClient", "AceError", "AceInfo", "AceStatus", "AceTimeout", "AceUnavailable", "DryerStatus",
    "FilamentInfo", "FrameDecoder", "FrameError", "SlotStatus", "crc16_mcrf4xx", "encode_frame",
]
