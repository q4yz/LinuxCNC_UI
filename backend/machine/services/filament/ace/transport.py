"""The ACE Pro's USB serial port (CDC-ACM, 115200 baud), for :class:`.client.AceClient`.

pyserial is blocking; reads run in a worker thread with a short timeout
so the client's loop stays responsive. A vanished port (USB unplugged,
the ACE restarting after 3 s of silence) raises ``OSError``.
"""
from __future__ import annotations

import asyncio
from typing import Any, Protocol

BAUD = 115200
READ_TIMEOUT_S = 0.05
WRITE_TIMEOUT_S = 0.5


class AceTransport(Protocol):
    async def open(self) -> None: ...
    async def close(self) -> None: ...
    async def write(self, data: bytes) -> None: ...
    async def read(self) -> bytes:
        """Bytes received so far (``b""`` after a short wait); ``OSError`` when gone."""
        ...


class SerialTransport:
    def __init__(self, port: str, baud: int = BAUD) -> None:
        self.port = port
        self.baud = baud
        self._serial: Any = None

    async def open(self) -> None:
        import serial  # pyserial — only needed with real hardware

        def _open() -> Any:
            return serial.Serial(self.port, self.baud, timeout=READ_TIMEOUT_S, write_timeout=WRITE_TIMEOUT_S)

        self._serial = await asyncio.to_thread(_open)

    async def close(self) -> None:
        port, self._serial = self._serial, None
        if port is not None:
            await asyncio.to_thread(port.close)

    async def write(self, data: bytes) -> None:
        if self._serial is None:
            raise OSError("ACE port not open")
        await asyncio.to_thread(self._serial.write, data)

    async def read(self) -> bytes:
        if self._serial is None:
            raise OSError("ACE port not open")
        data = await asyncio.to_thread(self._serial.read, 4096)
        return bytes(data)


__all__ = ["BAUD", "AceTransport", "SerialTransport"]
