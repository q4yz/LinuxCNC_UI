"""Tests for the lazy NML channel wrapper in ``hardware.connection``.

The backend must boot independently of whether LinuxCNC is running.
These tests exercise the :class:`_LazyChannel` wrapper directly
plus the public :func:`execute_sync_cmd` 503-when-offline contract.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi import HTTPException

from hardware.connection import (
    INITIAL_BACKOFF_S,
    _LazyChannel,
    _cmd_ch,
    execute_sync_cmd,
)


@pytest.fixture()
def fresh_lazy_channel(monkeypatch):
    """Return a fresh ``_LazyChannel`` for an isolated fake constructor.

    The fake ctor counts how many times it was invoked and can be
    patched to raise or succeed on a per-call basis. Each test
    starts with a fresh instance so the backoff state from one
    test cannot leak into another.
    """
    class FakeCtor:
        def __init__(self):
            self.calls = 0
            self.behaviour = "ok"  # "ok" | "raise"
            self.payload = object()

        def __call__(self):
            self.calls += 1
            if self.behaviour == "raise":
                raise OSError("NML channel unreachable")
            return self.payload

    fake = FakeCtor()
    # Build a wrapper that talks to ``fake`` instead of ``linuxcnc``.
    ch = _LazyChannel.__new__(_LazyChannel)
    ch._ctor_name = "fake"
    ch._ctor = fake
    ch._cached = None
    ch._lock = threading.Lock()
    ch._last_error_at = None
    ch._backoff_s = INITIAL_BACKOFF_S
    ch._attempt_count = 0
    yield ch, fake


def test_lazy_channel_returns_value_on_success(fresh_lazy_channel):
    """A healthy constructor returns the channel on first call."""
    ch, fake = fresh_lazy_channel
    assert ch.get() is fake.payload
    assert ch.is_connected() is True
    assert fake.calls == 1


def test_lazy_channel_returns_none_when_constructor_raises(fresh_lazy_channel):
    """When the constructor raises, the wrapper returns ``None``."""
    ch, fake = fresh_lazy_channel
    fake.behaviour = "raise"

    assert ch.get() is None
    assert ch.is_connected() is False
    assert fake.calls == 1


def test_lazy_channel_retries_on_subsequent_calls(fresh_lazy_channel):
    """After the backoff window elapses the wrapper retries."""
    ch, fake = fresh_lazy_channel
    fake.behaviour = "raise"
    assert ch.get() is None

    # Fast-forward past the initial 1 s backoff by reaching into
    # the wrapper's monotonic timestamp.
    ch._last_error_at = time.monotonic() - 10.0
    # Switch to a healthy constructor and confirm the retry lands.
    fake.behaviour = "ok"
    assert ch.get() is fake.payload
    assert ch.is_connected() is True
    assert fake.calls == 2


def test_lazy_channel_rate_limits_within_backoff_window(fresh_lazy_channel):
    """Successive failures inside the backoff window do not retry."""
    ch, fake = fresh_lazy_channel
    fake.behaviour = "raise"

    # First call records the failure and timestamps it.
    assert ch.get() is None
    # Second call inside the backoff window returns ``None`` without
    # re-invoking the constructor.
    assert ch.get() is None
    assert fake.calls == 1


def test_execute_sync_cmd_returns_503_when_channel_offline(
    fresh_lazy_channel, monkeypatch
):
    """``execute_sync_cmd`` raises HTTPException(503) when the
    command channel has not yet connected.
    """
    # Force the command channel to report offline by pointing it
    # at a constructor that raises. The ``monkeypatch`` fixture
    # restores the original on teardown.
    fake_cmd = fresh_lazy_channel[1]
    fake_cmd.behaviour = "raise"
    monkeypatch.setattr(_cmd_ch, "_ctor", fake_cmd)
    monkeypatch.setattr(_cmd_ch, "_cached", None)
    monkeypatch.setattr(_cmd_ch, "_last_error_at", None)
    monkeypatch.setattr(_cmd_ch, "_backoff_s", INITIAL_BACKOFF_S)

    with pytest.raises(HTTPException) as excinfo:
        execute_sync_cmd("mode", 0, 1)
    assert excinfo.value.status_code == 503
    assert "linuxcnc" in excinfo.value.detail.lower()
