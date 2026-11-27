"""ACE Pro frames: ``FF AA | len (u16 LE) | JSON | CRC-16/MCRF4XX (u16 LE) | FE``.

The length and the CRC cover the JSON bytes only. The ACE has no flow
control and no recovery from a bad header: a frame whose JSON exceeds
:data:`MAX_PAYLOAD` freezes it until power-cycled, and a CRC that
happens to read ``FF AA`` can look like a new header — :func:`encode_frame`
refuses the first and pads the JSON away from the second.
"""
from __future__ import annotations

import json
from typing import Any

HEADER = b"\xff\xaa"
TRAILER = 0xFE
#: Largest JSON the ACE survives (bytes).
MAX_PAYLOAD = 1024
#: Header + length + CRC + trailer.
OVERHEAD = 2 + 2 + 2 + 1


class FrameError(ValueError):
    """A frame that must not be sent (too large, not JSON-able)."""


def crc16_mcrf4xx(data: bytes) -> int:
    """CRC-16/MCRF4XX: poly 0x1021 reflected (0x8408), init 0xFFFF, no final XOR."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc


def _frame(payload: bytes) -> bytes:
    crc = crc16_mcrf4xx(payload)
    return HEADER + len(payload).to_bytes(2, "little") + payload + crc.to_bytes(2, "little") + bytes([TRAILER])


def encode_frame(message: dict[str, Any]) -> bytes:
    """One frame for ``message`` (compact JSON)."""
    try:
        payload = json.dumps(message, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise FrameError(f"not JSON: {exc}") from None
    if crc16_mcrf4xx(payload).to_bytes(2, "little") == HEADER:
        # a CRC reading FF AA could be taken for a header: change the JSON
        payload = json.dumps({**message, "_": 0}, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    if len(payload) > MAX_PAYLOAD:
        raise FrameError(f"{len(payload)} bytes of JSON: the ACE freezes above {MAX_PAYLOAD}")
    return _frame(payload)


class FrameDecoder:
    """Bytes in, messages out. Survives garbage, split frames and bad CRCs:
    whatever does not form a valid frame is skipped up to the next header."""

    def __init__(self) -> None:
        self._buf = bytearray()
        #: Frames dropped (bad length, CRC, trailer or JSON) — diagnostics.
        self.dropped = 0

    def reset(self) -> None:
        """Forget a partial frame (after a reconnect)."""
        self._buf.clear()

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        self._buf += data
        out: list[dict[str, Any]] = []
        while True:
            start = self._buf.find(HEADER)
            if start < 0:
                # keep a lone trailing FF: it may be the first header byte
                del self._buf[: max(0, len(self._buf) - 1)]
                return out
            if start:
                del self._buf[:start]
            if len(self._buf) < 4:
                return out
            length = int.from_bytes(self._buf[2:4], "little")
            if length > MAX_PAYLOAD:
                self._skip()
                continue
            end = 4 + length + 3
            if len(self._buf) < end:
                return out
            payload = bytes(self._buf[4: 4 + length])
            crc = int.from_bytes(self._buf[4 + length: 6 + length], "little")
            if self._buf[end - 1] != TRAILER or crc != crc16_mcrf4xx(payload):
                self._skip()
                continue
            del self._buf[:end]
            try:
                message = json.loads(payload)
            except ValueError:
                self.dropped += 1
                continue
            if isinstance(message, dict):
                out.append(message)
            else:
                self.dropped += 1

    def _skip(self) -> None:
        """Not a frame at this header: look for the next one."""
        self.dropped += 1
        del self._buf[:2]


__all__ = ["HEADER", "MAX_PAYLOAD", "FrameDecoder", "FrameError", "crc16_mcrf4xx", "encode_frame"]
