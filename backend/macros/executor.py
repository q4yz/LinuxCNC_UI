"""Execution engine for hybrid LinuxCNC macros."""
from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from hardware.connection import connection
from services.console_logger import get_console_logger

from . import MacroStore
from .parser import GCODEText, PythonBlock, parse
from .schemas import MacroEvent

logger = logging.getLogger(__name__)


class CNCInterface:
    def emit(self, gcode: str) -> None:
        try:
            connection.get_machine_cmd().mdi(gcode)
        except Exception:
            logger.exception("Failed to emit macro G-code")
            raise

    def log(self, message: str) -> None:
        get_console_logger().log_response(str(message))

    def get_pos(self) -> dict[str, float]:
        position = connection.get_machine_stat().actual_position
        return {axis: float(position[index]) for index, axis in enumerate(("x", "y", "z"))}


async def run_macro(name: str, params: dict[str, Any] | None = None, store: MacroStore | None = None) -> AsyncIterator[MacroEvent]:
    """Execute a stored macro and yield emitted events."""
    del uuid  # keep the execution API intentionally deterministic for callers
    macro_store = store or MacroStore()
    body = macro_store.read(name)
    cnc = CNCInterface()
    globals_dict = {"cnc": cnc, "math": math, "time": time, "params": params or {}, "__builtins__": __builtins__}
    for segment in parse(body):
        if isinstance(segment, GCODEText):
            for line in segment.text.splitlines():
                command = line.strip()
                if command and not command.startswith(";"):
                    cnc.emit(command)
                    yield MacroEvent(type="gcode", payload={"gcode": command})
        elif isinstance(segment, PythonBlock):
            try:
                exec(segment.code, globals_dict)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Macro Python block failed")
                yield MacroEvent(type="error", payload={"message": str(exc), "line": segment.line})
            await asyncio.sleep(0)
