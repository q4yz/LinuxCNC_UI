"""Execution engine for hybrid LinuxCNC macros."""
from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import AsyncIterator
from typing import Any

from hardware.connection import connection
from services.console_logger import get_console_logger

from . import MacroStore
from .parser import GCODEText, PythonBlock, parse
from .schemas import MacroEvent

logger = logging.getLogger(__name__)


class CNCInterface:
    """Real CNC interface that delegates to ``backend.hardware.connection``.

    The executor exposes this object to macro scripts as ``cnc``.
    ``cnc.log`` calls are captured so the executor can stream them
    back to the WebSocket consumer alongside emitted G-code.
    """

    def __init__(self) -> None:
        self._logs: list[str] = []

    def emit(self, gcode: str) -> None:
        try:
            connection.get_machine_cmd().mdi(gcode)
        except Exception:
            logger.exception("Failed to emit macro G-code")
            raise

    def log(self, message: str) -> None:
        text = str(message)
        self._logs.append(text)
        get_console_logger().log_response(text)

    def get_pos(self) -> dict[str, float]:
        position = connection.get_machine_stat().actual_position
        return {axis: float(position[index]) for index, axis in enumerate(("x", "y", "z"))}

    def drain_logs(self) -> list[str]:
        """Return and clear accumulated log messages.

        The executor calls this after every G-code emit and Python
        block so it can stream ``log`` events to the consumer.
        """
        messages = self._logs[:]
        self._logs.clear()
        return messages


class MockCNCInterface:
    """Hardware-less drop-in for tests and local dry-runs.

    Mirrors the ``CNCInterface`` surface but writes to the module
    logger instead of the real LinuxCNC command channel so a macro
    can be developed without a machine attached.
    """

    def __init__(self) -> None:
        self._logs: list[str] = []

    def emit(self, gcode: str) -> None:
        logger.info("[MOCK GCODE] %s", gcode)

    def log(self, message: str) -> None:
        text = str(message)
        self._logs.append(text)
        logger.info("[MOCK LOG] %s", text)

    def get_pos(self) -> dict[str, float]:
        return {"x": 0.0, "y": 0.0, "z": 10.0}

    def drain_logs(self) -> list[str]:
        """Return and clear accumulated log messages."""
        messages = self._logs[:]
        self._logs.clear()
        return messages


def build_globals(cnc: CNCInterface | MockCNCInterface, params: dict[str, Any] | None) -> dict[str, Any]:
    """Build the globals dict passed to ``exec()`` for a macro Python block.

    Exposes ``cnc``, the real ``math`` module, the ``time`` module,
    and the user-supplied ``params`` mapping so macro scripts can
    call ``cnc.emit`` / ``cnc.log`` / ``cnc.get_pos`` and read
    parameters without any extra wiring.
    """
    return {
        "cnc": cnc,
        "math": math,
        "time": time,
        "params": params or {},
    }


def _drain_log_events(cnc: CNCInterface | MockCNCInterface) -> list[MacroEvent]:
    """Convert accumulated ``cnc.log`` messages into ``MacroEvent`` rows."""
    return [MacroEvent(type="log", payload={"message": msg}) for msg in cnc.drain_logs()]


async def run_macro(
    name: str,
    params: dict[str, Any] | None = None,
    store: MacroStore | None = None,
    cnc: CNCInterface | MockCNCInterface | None = None,
) -> AsyncIterator[MacroEvent]:
    """Execute a stored macro and yield ``MacroEvent`` rows.

    Streams ``log`` events from ``cnc.log`` calls, ``gcode`` events
    for every non-comment line that leaves ``cnc.emit``, ``error``
    events when a Python block or G-code emit raises, and a final
    ``done`` event so consumers know the run finished.
    """
    macro_store = store or MacroStore()
    body = macro_store.read(name)
    if cnc is None:
        cnc = CNCInterface()
    globals_dict = build_globals(cnc, params)
    for segment in parse(body):
        if isinstance(segment, GCODEText):
            for raw_line in segment.text.splitlines():
                command = raw_line.strip()
                if not command or command.startswith(";"):
                    continue
                try:
                    cnc.emit(command)
                except Exception as exc:  # noqa: BLE001 - surfaced as event
                    logger.exception("Macro G-code emit failed")
                    yield MacroEvent(type="error", payload={"message": str(exc)})
                else:
                    yield MacroEvent(type="gcode", payload={"gcode": command})
                for event in _drain_log_events(cnc):
                    yield event
        elif isinstance(segment, PythonBlock):
            try:
                exec(segment.code, globals_dict)
            except Exception as exc:  # noqa: BLE001 - surfaced as event
                logger.exception("Macro Python block failed")
                yield MacroEvent(type="error", payload={"message": str(exc), "line": segment.line})
            for event in _drain_log_events(cnc):
                yield event
            await asyncio.sleep(0)
    yield MacroEvent(type="done", payload={"name": name})
