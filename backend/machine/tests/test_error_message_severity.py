"""Error-channel kind -> severity.

G-code ``(MSG, ...)`` arrives on LinuxCNC's error channel as an
``OPERATOR_DISPLAY`` entry — an operator message, not a fault — while
``(ABORT, ...)`` arrives as ``OPERATOR_ERROR``. The UI must only show
the latter as an error.
"""
from __future__ import annotations

from unittest.mock import patch

from dtos.LinuxCNCError import LinuxCNCError
from hardware.Connection import linuxcnc, message_severity


def test_operator_messages_are_info():
    for name in ("OPERATOR_DISPLAY", "OPERATOR_TEXT", "NML_TEXT", "NML_DISPLAY"):
        assert message_severity(getattr(linuxcnc, name)) == "info", name


def test_errors_and_unknown_kinds_are_errors():
    assert message_severity(linuxcnc.OPERATOR_ERROR) == "error"
    assert message_severity(linuxcnc.NML_ERROR) == "error"
    # An unrecognised kind must never be downgraded to info.
    assert message_severity(0) == "error"
    assert message_severity(999) == "error"


def test_mock_kinds_match_real_python_linuxcnc_values():
    """The frontend's kind table labels these integers — the mock must
    not invent its own numbering."""
    assert (linuxcnc.NML_ERROR, linuxcnc.NML_TEXT, linuxcnc.NML_DISPLAY) == (1, 2, 3)
    assert (linuxcnc.OPERATOR_ERROR, linuxcnc.OPERATOR_TEXT, linuxcnc.OPERATOR_DISPLAY) == (11, 12, 13)


def test_dto_defaults_to_error():
    assert LinuxCNCError(kind=1, text="x").severity == "error"


def test_error_history_entries_get_their_severity_stamped():
    from services.StateService import StateService

    history = [
        {"kind": linuxcnc.OPERATOR_DISPLAY, "text": "Bore Diameter is: 20.01", "time": None},
        {"kind": linuxcnc.OPERATOR_ERROR, "text": "Slow probe missed target!", "time": None},
        "bare string from real stat.errors",
    ]
    with patch("services.StateService.read_error_history", return_value=history):
        stamped = StateService().get_error_history()

    assert stamped[0]["severity"] == "info"
    assert stamped[1]["severity"] == "error"
    assert stamped[2] == "bare string from real stat.errors"
