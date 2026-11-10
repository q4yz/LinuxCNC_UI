"""The backend's own console messages (homing routine, Z tilt, bed mesh,
PROBE_ACCURACY, macros) reach the browser: ``log_event`` queues them for
the telemetry loop, which sends ``{"type": "console"}``. The MDI echo
and telemetry stay in the file only (the browser shows those itself)."""
from __future__ import annotations

from services.ConsoleLogger import OUTBOX_MAX, ConsoleLogger, LogLevel


def test_service_messages_are_published(tmp_path):
    log = ConsoleLogger(tmp_path / "c.log")
    log.log_event("Z_TILT_ADJUST round 1: point 1/3 X30 Y5 -> Z 0.1000", level=LogLevel.DEBUG, source="CMD")
    log.log_event("Z_TILT_ADJUST done after 2 round(s)", level=LogLevel.INFO, source="CMD")
    log.log_command("G0 X1")
    log.log_response("Executed: G0 X1")
    log.log_telemetry("{}")
    events = log.drain_published()
    assert [(e["level"], e["text"][:13]) for e in events] == [("debug", "Z_TILT_ADJUST"), ("info", "Z_TILT_ADJUST")]
    assert log.drain_published() == []
    assert (tmp_path / "c.log").read_text().count(chr(10)) == 5  # all of them in the file


def test_bounded_while_nobody_drains(tmp_path):
    log = ConsoleLogger(tmp_path / "c.log")
    for k in range(OUTBOX_MAX + 10):
        log.log_event(f"m{k}")
    events = log.drain_published()
    assert len(events) == OUTBOX_MAX and events[-1]["text"] == f"m{OUTBOX_MAX + 9}"
