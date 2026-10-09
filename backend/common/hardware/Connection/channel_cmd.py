"""Shared LinuxCNC command channel and thread-safe execution dispatchers.

``command`` (write/dispatch + ``wait_complete``) stays a single shared
channel, deliberately not split per-thread like ``stat``/
``error_channel`` — dispatching is operator-paced, not a hot polling
path, and ``wait_complete()``'s "did *my* command finish" tracking
assumes one in-flight command per object; giving every caller an
independent ``command`` channel would need its own synchronization
story (a lock around dispatch + ``wait_complete`` as one atomic unit)
that read-only ``stat``/``error_channel`` simply doesn't need.

``_cmd_lock`` serializes every dispatch+``wait_complete`` round-trip
through the shared ``command`` channel — real LinuxCNC task processes
one command at a time anyway, and ``wait_complete()``'s completion
tracking assumes one in-flight command per channel object. Without
this, two threads dispatching concurrently on the same ``command``
object can each observe the *other's* completion. Held for the whole
round-trip (including ``execute_gcode``'s MDI mode-switch preamble,
not just the final ``wait_complete``) so a mode switch from one call
can never interleave with another call's dispatch. NOT reentrant —
``_switch_to_mdi_mode``/``_wait_for_completion`` never acquire it
themselves, only the top-level ``execute_gcode``/``execute_sync_cmd``
callers do, exactly once each.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from .errors import (
    CommandError,
    CommandRejectedError,
    CommandTimeoutError,
    LinuxCNCUnavailableError,
)

from core.NonRepeatingLogger import NonRepeatingLogger

from .core import MachineMode, RcsStatus, _LazyChannel
from .channel_stat import get_stat_channel

logger = NonRepeatingLogger("backend.hardware.connection.channel_cmd")

_cmd_ch = _LazyChannel("command")
_cmd_lock = threading.Lock()


def get_cmd_channel() -> Optional[Any]:
    """Retrieve the underlying LinuxCNC command channel (shared)."""
    return _cmd_ch.get()


def is_cmd_connected() -> bool:
    """Whether the shared `command` channel has connected."""
    return _cmd_ch.is_connected()


# ---------------------------------------------------------------------------
# Private Helper Functions
# ---------------------------------------------------------------------------
def _wait_for_completion(cmd_channel: Any, timeout: float) -> None:
    """
    Block until the LinuxCNC command completes, fails, or times out.

    Args:
        cmd_channel: The active LinuxCNC command channel.
        timeout (float): The maximum time to wait in seconds.

    Raises:
        CommandRejectedError (400): If the command returns an execution error.
        CommandTimeoutError (408): If the command exceeds the timeout.
    """
    if timeout <= 0:
        return

    result = cmd_channel.wait_complete(timeout)

    if result == RcsStatus.DONE:
        return
    elif result == RcsStatus.ERROR:
        raise CommandRejectedError("Command execution error")
    else:
        raise CommandTimeoutError("Command timed out")


def _switch_to_mdi_mode(stat_channel: Any, cmd_channel: Any) -> None:
    """
    Safely switch the machine to MDI mode if it is not already in it.

    Args:
        stat_channel: The active LinuxCNC status channel.
        cmd_channel: The active LinuxCNC command channel.
    """
    stat_channel.poll()
    if stat_channel.task_mode != MachineMode.MDI:
        cmd_channel.mode(MachineMode.MDI)
        _wait_for_completion(cmd_channel, timeout=1.0)


# ---------------------------------------------------------------------------
# Public Execution Commands
# ---------------------------------------------------------------------------
def execute_gcode(gcode: str, timeout: float = 10.0) -> Dict[str, Any]:
    """
    Execute raw G-code via LinuxCNC MDI mode.

    Automatically switches the machine to MDI mode if required, sends the
    command, and awaits completion.

    Args:
        gcode (str): The G-code string to execute.
        timeout (float): The maximum wait time in seconds. Defaults to 10.0.

    Returns:
        dict: A status dictionary containing the executed G-code.

    Raises:
        LinuxCNCUnavailableError (503): If the LinuxCNC channels are unavailable.
        CommandRejectedError (400): If the G-code triggers an execution error.
        CommandTimeoutError (408): If the command times out.
        CommandError (500): On unexpected internal errors.
    """
    cmd = get_cmd_channel()
    stat = get_stat_channel()

    if cmd is None or stat is None:
        raise LinuxCNCUnavailableError("LinuxCNC is not running. Start LinuxCNC and retry.")

    try:
        with _cmd_lock:
            _switch_to_mdi_mode(stat, cmd)
            cmd.mdi(gcode)

            # We catch the inner exception from _wait_for_completion
            # and re-raise it with G-Code specific context if needed.
            try:
                _wait_for_completion(cmd, timeout)
            except CommandRejectedError:
                raise CommandRejectedError(f"G-code execution error: {gcode}")

        return {"status": "success", "gcode": gcode}

    except CommandError:
        # Re-raise known command errors (400, 408, 503) cleanly
        raise
    except Exception as e:  # noqa: BLE001
        logger.error("G-code execution failed: %s", e)
        raise CommandError(str(e))


def dispatch_mdi(gcode: str, ack_timeout: float = 1.0) -> Optional[int]:
    """
    Hand one MDI line to LinuxCNC without waiting for its motion to finish.

    Unlike :func:`execute_gcode`, ``_cmd_lock`` is only held for the
    mode switch, the dispatch and a short acknowledgement wait — never
    for the move itself. A long MDI move (a macro's ``G1``, a probe)
    would otherwise hold the lock for its whole duration and stall
    every other command, including a jog stop. Callers that need
    sequential execution wait for the interpreter to go idle
    themselves, outside the lock (see ``MacroExecutionService``).

    Args:
        gcode (str): The G-code line to dispatch.
        ack_timeout (float): How long to wait for LinuxCNC to accept
            the command. A timeout here is not an error — the line is
            still queued, just not finished.

    Returns:
        The command's serial number (compare against
        ``stat.echo_serial_number``), or ``None`` if the channel does
        not expose one.

    Raises:
        LinuxCNCUnavailableError (503): If the LinuxCNC channels are unavailable.
        CommandRejectedError (400): If LinuxCNC rejects the command.
        CommandError (500): On unexpected internal errors.
    """
    cmd = get_cmd_channel()
    stat = get_stat_channel()

    if cmd is None or stat is None:
        raise LinuxCNCUnavailableError("LinuxCNC is not running. Start LinuxCNC and retry.")

    try:
        with _cmd_lock:
            _switch_to_mdi_mode(stat, cmd)
            cmd.mdi(gcode)
            result = cmd.wait_complete(ack_timeout)
            serial = getattr(cmd, "serial", None)
    except CommandError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error("MDI dispatch failed: %s", e)
        raise CommandError(str(e))

    if result == RcsStatus.ERROR:
        raise CommandRejectedError(f"G-code execution error: {gcode}")
    return serial


def execute_sync_cmd(cmd_name: str, timeout: float = 0, *args) -> Dict[str, str]:
    """
    Dispatch a named command directly to the LinuxCNC command channel.

    Args:
        cmd_name (str): The exact name of the method to call on the command channel.
        timeout (float): How long to wait for completion in seconds (0 for async).
        *args: Variable arguments to pass to the command method.

    Returns:
        dict: A success status dictionary `{"status": "success"}`.

    Raises:
        LinuxCNCUnavailableError (503): If the LinuxCNC command channel is unavailable.
        CommandError (500): If the command does not exist or an internal error occurs.
        CommandRejectedError (400): If the command returns an execution error.
        CommandTimeoutError (408): If the command exceeds `timeout`.
    """
    cmd = get_cmd_channel()
    if cmd is None:
        raise LinuxCNCUnavailableError("LinuxCNC is not running. Start LinuxCNC and retry.")

    # 1. Resolve command binding
    try:
        func = getattr(cmd, cmd_name)
    except AttributeError:
        raise CommandError(f"Command '{cmd_name}' not implemented in hardware interface.")

    # 2. Execute and wait
    try:
        with _cmd_lock:
            func(*args)
            _wait_for_completion(cmd, timeout)
        return {"status": "success"}
    except CommandError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"Command execution failed: {e}")
        raise CommandError(str(e))


def ensure_mdi_mode() -> None:
    """Force the machine into MDI mode immediately with a standard 5-second timeout."""
    execute_sync_cmd("mode", 5.0, MachineMode.MDI)


__all__ = [
    "get_cmd_channel",
    "is_cmd_connected",
    "execute_gcode",
    "dispatch_mdi",
    "execute_sync_cmd",
    "ensure_mdi_mode",
]
