"""Regression tests for the ``joint`` flag in :mod:`jog_service`.

The LinuxCNC error ``JOG_CONT Mode is TELEOP, cannot jog joint``
fired on the operator's live machine because the previous
implementation labelled the second argument to
:func:`linuxcnc.command.jog` as ``teleop_flag`` and passed the
wrong value. The second argument is actually the ``joint`` flag —
``1`` for per-joint jogging, ``0`` for Cartesian jogging — and the
correct mapping is the **inverse** of the system mode.

These tests pin the corrected mapping directly. A contributor
who reverts to the ``teleop_flag`` naming (or inverts the values)
will trip the test that the operator's live logs surfaced.
"""
from __future__ import annotations

from typing import List, Tuple

import pytest

from modules.axis import jog_service


class _RecordingStat:
    """Stub for ``linuxcnc.stat()`` that records the system mode.

    The mock used in the other axis tests lacks ``motion_mode``
    entirely — these tests need the attribute, so we ship our own
    recording stub. The fixture-driven integration tests in
    ``test_jog_keepalive.py`` / ``test_jog_watchdog.py`` use the
    shared mock; this file targets the ``joint`` flag directly.
    """

    TELEOP = 3

    def __init__(self, mode: int):
        self.motion_mode = mode
        self.poll_count = 0

    def poll(self):
        self.poll_count += 1


class _RecordingClient:
    """Stub for the ``hardware.execute_sync_cmd`` callable.

    Captures every call so the test can assert on the ``joint_flag``
    value without poking into the linuxcnc internals. The actual
    call signatures vary (``execute_sync_cmd("mode", timeout, mode_id)``
    vs ``execute_sync_cmd("jog", timeout, tag, joint, axis, *args)``)
    so we accept variable positional args.
    """

    def __init__(self):
        # ``calls`` stores the full ``(name, timeout, *rest)`` tuple
        # for every dispatch; tests that care about specific shapes
        # (``jog`` calls) inspect ``rest``.
        self.calls: List[Tuple] = []

    def __call__(self, name, timeout, *rest):
        self.calls.append((name, timeout, *rest))


class _FakeStatFactory:
    """Callable that returns the same recording stat on each call.

    The supervisor's :func:`jog_axis` calls ``linuxcnc.stat()`` to
    get a fresh stat object, then ``s.poll()`` to refresh it. A
    factory lets us hand it the same stat instance for every call
    so the test can assert on a single state vector.
    """

    def __init__(self, mode: int):
        self.stat = _RecordingStat(mode)

    def __call__(self):
        return self.stat


@pytest.fixture()
def recording_client(monkeypatch):
    """Install a recording ``execute_sync_cmd`` and return it."""
    client = _RecordingClient()
    monkeypatch.setattr(jog_service, "execute_sync_cmd", client)
    return client


@pytest.fixture()
def teleop_stat(monkeypatch):
    """Stat stub that reports ``TRAJ_MODE_TELEOP``."""
    factory = _FakeStatFactory(_RecordingStat.TELEOP)
    monkeypatch.setattr(jog_service.linuxcnc, "stat", factory)
    return factory.stat


@pytest.fixture()
def free_stat(monkeypatch):
    """Stat stub that reports ``TRAJ_MODE_FREE`` (per-joint)."""
    factory = _FakeStatFactory(_RecordingStat.TELEOP - 1)
    monkeypatch.setattr(jog_service.linuxcnc, "stat", factory)
    return factory.stat


# ────────────────────────────────────────────────────────────────────── #
# jog_axis — the headline regression                                       #
# ────────────────────────────────────────────────────────────────────── #


def test_jog_axis_sends_joint_flag_1_when_system_in_free_mode(
    recording_client, free_stat
):
    """Per-joint jogging sends ``joint=1``.

    When the system is in FREE / JOINT mode (``motion_mode !=
    TELEOP``) the operator's per-joint request must carry
    ``joint=1``. The previous implementation sent ``joint=0`` here
    (labelled ``teleop_flag``), which silently disabled joint
    jogging while the system was in FREE mode. This test is the
    smoking gun for that regression.
    """
    jog_service.jog_axis({0: 1000.0}, distance=0.0)
    # ``execute_sync_cmd("jog", timeout, tag, joint, axis, velocity)``.
    # The recording client's ``calls`` stores ``(name, timeout, *rest)``
    # — for ``jog_axis({0: ...}, distance=0)`` the trailing args
    # are ``(tag, joint, axis, velocity)``.
    jog_calls = [c for c in recording_client.calls if c[0] == "jog"]
    assert jog_calls, "no execute_sync_cmd('jog', ...) call recorded"
    name, _timeout, tag, joint, axis, _velocity = jog_calls[-1]
    assert tag == jog_service.linuxcnc.JOG_CONTINUOUS
    assert joint == 1, (
        "expected joint=1 in FREE mode (per-joint jogging); the "
        "previous bug sent joint=0 with the variable labelled "
        "'teleop_flag'."
    )
    assert axis == 0


def test_jog_axis_sends_joint_flag_0_when_system_in_teleop_mode(
    recording_client, teleop_stat
):
    """Cartesian jogging sends ``joint=0``.

    When the system is in TELEOP mode, ``joint`` must be ``0``.
    The previous implementation sent ``joint=1`` here (because the
    variable was ``teleop_flag`` and TELEOP is encoded as ``1``),
    which LinuxCNC rejects with "Mode is TELEOP, cannot jog joint".
    That error fired on the operator's live machine on every
    continuous jog attempt. This test is the headline regression.
    """
    jog_service.jog_axis({0: 1000.0}, distance=0.0)
    jog_calls = [c for c in recording_client.calls if c[0] == "jog"]
    assert jog_calls, "no execute_sync_cmd('jog', ...) call recorded"
    name, _timeout, tag, joint, axis, _velocity = jog_calls[-1]
    assert tag == jog_service.linuxcnc.JOG_CONTINUOUS
    assert joint == 0, (
        "expected joint=0 in TELEOP mode (Cartesian jogging); the "
        "previous bug sent joint=1, which LinuxCNC rejects with "
        "'JOG_CONT Mode is TELEOP, cannot jog joint'."
    )


def test_jog_axis_step_jog_carries_same_joint_flag(
    recording_client, teleop_stat
):
    """Step jogs (``distance != 0``) carry the same corrected flag.

    The previous bug was the same for continuous and step jogs —
    both called ``execute_sync_cmd`` with the wrong ``joint``
    value. Pin both code paths so a future contributor cannot
    revert one without tripping the other.
    """
    jog_service.jog_axis({0: 500.0}, distance=5.0)
    jog_calls = [c for c in recording_client.calls if c[0] == "jog"]
    assert jog_calls, "no execute_sync_cmd('jog', ...) call recorded"
    name, _timeout, tag, joint, _axis, _velocity, _distance = jog_calls[-1]
    assert tag == jog_service.linuxcnc.JOG_INCREMENT
    assert joint == 0  # system is in TELEOP for this test


# ────────────────────────────────────────────────────────────────────── #
# stop_axis — the related bug (STOP also takes joint)                      #
# ────────────────────────────────────────────────────────────────────── #


def test_stop_axis_sends_joint_flag_1_in_free_mode(
    recording_client, free_stat
):
    """Per-joint jog stops carry ``joint=1`` to halt the right axis.

    LinuxCNC disambiguates which jog to stop based on the ``joint``
    flag passed to ``command.jog(tag=JOG_STOP, ...)``. A jog
    started with ``joint=1`` (per-joint) needs a stop with the
    same flag — otherwise the JOG_STOP silently targets a
    non-existent Cartesian jog. Pin this so a contributor who
    fixes ``jog_axis`` but forgets ``stop_axis`` does not silently
    regress the watchdog.
    """
    jog_service.stop_axis(0)
    jog_calls = [c for c in recording_client.calls if c[0] == "jog"]
    assert jog_calls, "no execute_sync_cmd('jog', ...) call recorded"
    name, _timeout, tag, joint, axis = jog_calls[-1]
    assert tag == jog_service.linuxcnc.JOG_STOP
    assert joint == 1


def test_stop_axis_sends_joint_flag_0_in_teleop_mode(
    recording_client, teleop_stat
):
    """Cartesian jog stops carry ``joint=0``.

    Mirror of the per-joint test above. Pinning the inverted
    mapping in ``stop_axis`` is critical because the watchdog
    calls ``stop_axis`` on every expired entry — a wrong flag
    would silently miss the actual jog.
    """
    jog_service.stop_axis(0)
    jog_calls = [c for c in recording_client.calls if c[0] == "jog"]
    assert jog_calls, "no execute_sync_cmd('jog', ...) call recorded"
    name, _timeout, tag, joint, axis = jog_calls[-1]
    assert tag == jog_service.linuxcnc.JOG_STOP
    assert joint == 0


# ────────────────────────────────────────────────────────────────────── #
# Self-healing removed                                                     #
# ────────────────────────────────────────────────────────────────────── #


def test_jog_axis_does_not_force_teleop_on_homed_machine(
    recording_client, free_stat, monkeypatch
):
    """The previous self-healing block forced TELEOP on every homed
    machine, which was the wrong direction for per-joint jogging.

    The current implementation trusts the operator's existing mode
    — no implicit ``teleop_enable(1)`` calls inside ``jog_axis``.
    Pin the absence so a contributor who re-adds the block sees a
    clear test failure (the recording client would log an
    unexpected ``teleop_enable`` call).
    """
    calls_seen = []

    def tracking_execute_sync_cmd(name, timeout, *args):
        calls_seen.append((name, args))
        # Don't actually dispatch — the test asserts only on the
        # absence of ``teleop_enable`` calls.

    monkeypatch.setattr(jog_service, "execute_sync_cmd", tracking_execute_sync_cmd)
    jog_service.jog_axis({0: 1000.0}, distance=0.0)

    teleop_enable_calls = [
        c for c in calls_seen
        if c[0] == "teleop_enable"
    ]
    assert teleop_enable_calls == [], (
        "jog_axis must not implicitly toggle teleop_enable — the "
        "previous self-healing block forced TELEOP on every homed "
        "machine, which broke per-joint jogging. If a future race "
        "needs mode-switching, do it explicitly from the operator's "
        "action, not implicitly here."
    )


# ────────────────────────────────────────────────────────────────────── #
# Wiring — make sure the service module is what the WS dispatcher uses  #
# ────────────────────────────────────────────────────────────────────── #


def test_module_exposes_canonical_function_names():
    """The dispatcher in ``servo_thread.py`` imports these names.

    A rename (e.g. back to ``ws_jog_*``) without updating the
    dispatcher would break the WebSocket path silently. Pin the
    public surface.
    """
    assert hasattr(jog_service, "jog_axis")
    assert hasattr(jog_service, "jog_stop")
    assert hasattr(jog_service, "jog_keepalive")
    assert hasattr(jog_service, "stop_axis")
