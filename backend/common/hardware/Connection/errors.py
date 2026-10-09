"""Errors raised by the LinuxCNC command channel.

The hardware layer does not know about HTTP. Each error carries the
``status_code`` / ``detail`` pair the HTTP edge answers with;
:func:`exceptions.http.register_command_error_handler` turns them into
responses for the machine app.
"""
from __future__ import annotations


class CommandError(Exception):
    """A command to LinuxCNC failed (unexpected internal error)."""

    status_code = 500

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class CommandRejectedError(CommandError):
    """LinuxCNC answered the command with an execution error."""

    status_code = 400


class CommandTimeoutError(CommandError):
    """The command did not complete within its timeout."""

    status_code = 408


class LinuxCNCUnavailableError(CommandError):
    """The command channel is not connected (LinuxCNC not running)."""

    status_code = 503


__all__ = [
    "CommandError",
    "CommandRejectedError",
    "CommandTimeoutError",
    "LinuxCNCUnavailableError",
]
