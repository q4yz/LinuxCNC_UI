"""Hybrid executor for the macro subsystem (issue #7).

Running a macro is a three-step pipeline:

1. :func:`parse_macro` splits the file into ``gcode`` and
   ``python`` blocks.
2. The executor walks the blocks sequentially. G-code blocks are
   streamed to the LinuxCNC command interface (mock-compatible);
   Python blocks are compiled and executed with a curated
   ``globals()`` dict that exposes ``cnc``, ``math``, and the
   built-ins.
3. The run produces a :class:`MacroRunResponse` — a JSON-serialisable
   record of every emitted G-code line, every ``cnc.log`` call,
   and any exception traceback.

The executor runs the walk in a worker thread via
``asyncio.to_thread`` so the FastAPI event loop stays free even
when a Python block does heavy work. The default :class:`CNCInterface`
talks to ``hardware.connection``, so the same code path works
against the real LinuxCNC binding and the mock.
"""

from __future__ import annotations

import asyncio
import builtins as _builtins
import logging
import math
import traceback
from typing import Any, Dict, List, Optional

from core.macro_models import MacroLogEntry, MacroRunResponse
from hardware.connection import connection
from .macro_parser import parse_macro

logger = logging.getLogger("backend.services.macro_executor")


class CNCInterface:
    """Object exposed to Python blocks as ``cnc``.

    Every method delegates to ``backend/hardware/connection.py`` so
    the executor stays mock-compatible. ``log`` and ``emit`` are
    also pushed into the ``MacroRunResponse`` so the frontend can
    render them in the editor console without polling the backend
    persistent logger.
    """

    def __init__(self) -> None:
        self._emitted: List[str] = []
        self._logs: List[MacroLogEntry] = []

    # ------------------------------------------------------------------ #
    # Public surface (called from ``exec``)                                #
    # ------------------------------------------------------------------ #

    def emit(self, gcode: str) -> None:
        """Send ``gcode`` to the controller.

        ``gcode`` may be a single line or a multi-line string; the
        executor concatenates whatever the user passes verbatim.
        Empty / whitespace-only lines are dropped so the
        interpreter log stays uncluttered.
        """
        if not isinstance(gcode, str):
            gcode = str(gcode)
        for raw in gcode.splitlines():
            line = raw.strip()
            if not line:
                continue
            self._emitted.append(line)
            logger.info("[macro] -> %s", line)
            try:
                connection.execute_sync_cmd("mdi", 0, line)
            except Exception as exc:  # noqa: BLE001 - surface to frontend
                logger.warning("macro emit failed for %s: %s", line, exc)
                raise

    def log(self, message: Any) -> None:
        """Record a log entry in the run response.

        Anything ``str()`` can represent is accepted; the value is
        also echoed through the standard ``logging`` module so the
        persistent console history picks it up.
        """
        text = message if isinstance(message, str) else str(message)
        self._logs.append(MacroLogEntry(level="info", message=text))
        logger.info("[macro log] %s", text)

    def warn(self, message: Any) -> None:
        """Same as :meth:`log` but tagged as a warning."""
        text = message if isinstance(message, str) else str(message)
        self._logs.append(MacroLogEntry(level="warning", message=text))
        logger.warning("[macro warn] %s", text)

    def get_pos(self) -> Dict[str, float]:
        """Best-effort position probe.

        Falls back to ``{"x": 0.0, "y": 0.0, "z": 0.0}`` when the
        hardware layer does not expose ``position``; the editor
        relies on the response to render a "where is the head"
        hint.
        """
        try:
            stat = connection.get_machine_stat()
            pos = getattr(stat, "position", None) or getattr(stat, "actual_position", None)
            if pos:
                # ``stat.position`` is a tuple of 9 floats in LinuxCNC.
                return {
                    "x": float(pos[0]),
                    "y": float(pos[1]),
                    "z": float(pos[2]),
                }
        except Exception as exc:  # noqa: BLE001 - defensive
            logger.debug("macro get_pos failed: %s", exc)
        return {"x": 0.0, "y": 0.0, "z": 0.0}

    # ------------------------------------------------------------------ #
    # Used by the executor to pull the collected state                     #
    # ------------------------------------------------------------------ #

    def consume(self) -> Dict[str, List[Any]]:
        """Return and reset the ``emit`` / ``log`` buffers."""
        payload = {"emitted": list(self._emitted), "logs": list(self._logs)}
        self._emitted.clear()
        self._logs.clear()
        return payload


def _execute_sync(content: str) -> MacroRunResponse:
    """Walk the parsed blocks inside the worker thread.

    The function is intentionally synchronous — it is invoked from
    :func:`asyncio.to_thread` so the event loop is not blocked.
    """
    cnc = CNCInterface()
    response = MacroRunResponse(ok=True, logs=[], emitted=[], error=None)

    try:
        blocks = parse_macro(content)
    except Exception as exc:  # noqa: BLE001
        logger.error("macro parser failed: %s", exc)
        return MacroRunResponse(
            ok=False,
            logs=[
                MacroLogEntry(level="error", message=f"Parser failed: {exc}"),
            ],
            emitted=[],
            error=traceback.format_exc(),
        )

    for block in blocks:
        if block["kind"] == "gcode":
            text = block["text"]
            if not text.strip():
                continue
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                response.emitted.append(line)
                logger.info("[macro] -> %s", line)
                try:
                    connection.execute_sync_cmd("mdi", 0, line)
                except Exception as exc:  # noqa: BLE001
                    response.ok = False
                    response.error = (
                        f"G-code execution failed at line {line!r}: {exc}"
                    )
                    response.logs.append(
                        MacroLogEntry(level="error", message=response.error),
                    )
                    return response
            continue

        # Python block.
        code = block["code"]
        # Build a fresh ``globals`` dict per block so a previous
        # run's state never leaks. ``__builtins__`` is the dict
        # form so user code can call ``len()``, ``range()`` etc.
        macro_globals: Dict[str, Any] = {
            "cnc": cnc,
            "math": math,
            "__builtins__": _builtins.__dict__,
        }
        try:
            exec(compile(code, "<macro>", "exec"), macro_globals)  # noqa: S102
        except Exception as exc:  # noqa: BLE001
            response.ok = False
            response.error = traceback.format_exc()
            response.logs.append(
                MacroLogEntry(level="error", message=f"Python error: {exc}"),
            )
            return response

    # Flush any leftover buffered messages.
    leftover = cnc.consume()
    response.emitted.extend(leftover["emitted"])
    response.logs.extend(leftover["logs"])
    return response


async def execute_macro(content: str) -> MacroRunResponse:
    """Async entry point used by the FastAPI route.

    Off-loads the synchronous walk to a worker thread so the event
    loop is not blocked by long-running Python blocks.
    """
    return await asyncio.to_thread(_execute_sync, content)


__all__ = ["CNCInterface", "execute_macro"]
