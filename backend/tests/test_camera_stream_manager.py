"""Tests for the on-demand StreamManager introduced in Issue #56.

The previous implementation kept a background thread that held the
OpenCV capture open continuously. Issue #56 enforces the opposite
contract:

* No camera handle is open until a client requests a stream.
* Switching cameras releases the previous capture immediately.
* The last client disconnecting releases the capture immediately.
* Invalid IDs (``""``, nonexistent path, cv2 import failure) raise
  actionable errors rather than crashing the worker.

These tests stub ``cv2.VideoCapture`` with an in-memory fake so the
on-demand lifecycle can be exercised without real hardware.
"""
from __future__ import annotations

import threading
from typing import List

import pytest

from modules.camera.router import StreamManager


# ---------------------------------------------------------------------- #
# Fake cv2.VideoCapture                                                   #
# ---------------------------------------------------------------------- #


class _FakeCapture:
    """Thread-safe in-memory replacement for ``cv2.VideoCapture``.

    Tracks ``opened``, ``released``, and ``read`` outcomes so the
    StreamManager lifecycle can be asserted end-to-end.
    """

    instances: List["_FakeCapture"] = []

    def __init__(self, source):
        self.source = source
        self.opened = True
        self.released = False
        self._reads = 0
        # The OpenCV API allows setting these even before ``read``.
        self.width = 0
        self.height = 0
        _FakeCapture.instances.append(self)

    @classmethod
    def reset(cls):
        cls.instances = []

    def isOpened(self) -> bool:
        return self.opened and not self.released

    def set(self, prop, value):
        # Only the props we use in the router; everything else is a no-op.
        # We don't import cv2 constants — instead we just record the
        # values the router would have set.
        self.width = int(value) if prop == 3 else self.width  # CAP_PROP_FRAME_WIDTH
        self.height = int(value) if prop == 4 else self.height  # CAP_PROP_FRAME_HEIGHT
        return True

    def read(self):
        self._reads += 1
        # Always succeed; the generator layer is not under test here.
        return True, b"frame-bytes"

    def release(self):
        self.released = True
        self.opened = False


class _RefusingCapture(_FakeCapture):
    """A ``_FakeCapture`` that reports ``isOpened() is False``."""

    def isOpened(self) -> bool:
        return False

    def __init__(self, source):
        super().__init__(source)


class _FakeCv2:
    """Minimal stub for the cv2 attributes StreamManager uses."""

    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    IMWRITE_JPEG_QUALITY = 1
    CAP_ANY = 0
    CAP_MSMF = 1400
    CAP_DSHOW = 700

    def __init__(self):
        self.VideoCapture = self._make_capture
        self.imencode = self._imencode

    def _make_capture(self, source, backend_api=None):
        return _FakeCapture(source)

    def _imencode(self, _ext, _frame, params):
        # Return a small deterministic JPEG-like buffer.
        return True, b"\xff\xd8\xff\xe0fake-jpeg"


@pytest.fixture()
def fake_cv2(monkeypatch):
    """Patch ``cv2`` inside the camera router with the in-memory fake.

    Returns the *same* instance installed in ``sys.modules`` so the
    tests can override ``cv2.VideoCapture`` and observe the change
    when the router calls ``import cv2`` inside ``acquire()``.
    """
    import sys

    import modules.camera.router as router_module

    fake = _FakeCv2()
    monkeypatch.setattr(router_module, "cv2", fake, raising=False)
    monkeypatch.setitem(sys.modules, "cv2", fake)
    _FakeCapture.reset()
    return fake


# ---------------------------------------------------------------------- #
# acquire / release                                                       #
# ---------------------------------------------------------------------- #


def test_acquire_then_release_opens_and_closes_capture(fake_cv2):
    manager = StreamManager()

    cap = manager.acquire("/dev/video0")
    assert isinstance(cap, _FakeCapture)
    assert cap.source == "/dev/video0"
    assert not cap.released

    snap = manager.status()
    assert snap["running"] is True
    assert snap["active_id"] == "/dev/video0"
    assert snap["refcount"] == 1

    manager.release("/dev/video0")
    snap = manager.status()
    assert snap["running"] is False
    assert snap["active_id"] is None
    assert snap["refcount"] == 0
    assert cap.released is True


def test_release_against_stale_id_is_noop(fake_cv2):
    """Releasing an id that is not active must not raise or touch state."""
    manager = StreamManager()
    manager.acquire("/dev/video0")
    # ``/dev/video1`` was never opened.
    manager.release("/dev/video1")
    snap = manager.status()
    assert snap["active_id"] == "/dev/video0"
    assert snap["refcount"] == 1


def test_switching_cameras_releases_previous(fake_cv2):
    """Opening a second camera must close the first immediately."""
    manager = StreamManager()

    cap0 = manager.acquire("/dev/video0")
    cap1 = manager.acquire("/dev/video1")

    assert cap0.released is True
    assert cap1.released is False
    snap = manager.status()
    assert snap["active_id"] == "/dev/video1"
    assert snap["refcount"] == 1


def test_double_acquire_shares_capture(fake_cv2):
    """Two concurrent requests for the same id share one capture."""
    manager = StreamManager()

    cap_a = manager.acquire("/dev/video0")
    cap_b = manager.acquire("/dev/video0")

    assert cap_a is cap_b
    snap = manager.status()
    assert snap["refcount"] == 2

    # Only the *last* release frees the hardware.
    manager.release("/dev/video0")
    snap = manager.status()
    assert snap["refcount"] == 1
    assert snap["active_id"] == "/dev/video0"

    manager.release("/dev/video0")
    snap = manager.status()
    assert snap["refcount"] == 0
    assert snap["active_id"] is None
    assert cap_a.released is True


def test_acquire_empty_id_raises(fake_cv2):
    manager = StreamManager()
    with pytest.raises(RuntimeError, match="camera_id is required"):
        manager.acquire("")


def test_acquire_unopenable_id_raises(fake_cv2):
    """If OpenCV refuses to open the device the manager raises."""
    manager = StreamManager()
    # Override the fake to refuse the next capture.
    _FakeCapture.instances.clear()
    original = fake_cv2.VideoCapture

    fake_cv2.VideoCapture = lambda source, backend_api=None: _RefusingCapture(source)
    with pytest.raises(RuntimeError, match="Cannot open camera source"):
        manager.acquire("/dev/video99")
    fake_cv2.VideoCapture = original

    snap = manager.status()
    assert snap["running"] is False
    assert snap["active_id"] is None


def test_acquire_when_cv2_missing_raises(monkeypatch):
    """If cv2 cannot be imported the manager raises RuntimeError.

    Patches ``sys.modules['cv2']`` with a sentinel module whose
    attribute access raises ``ImportError``, mirroring what the
    router sees when the binary is genuinely unavailable.
    """
    import sys
    import types

    import modules.camera.router as router_module

    class _BrokenCv2(types.ModuleType):
        def __getattr__(self, name):
            raise ImportError("synthetic cv2 import failure")

    broken_cv2 = _BrokenCv2("cv2")
    monkeypatch.setitem(sys.modules, "cv2", broken_cv2)
    # Drop the cache so the router's ``import cv2`` falls through.
    monkeypatch.setattr(router_module, "_cv2_disabled", False, raising=False)

    manager = StreamManager()
    with pytest.raises(RuntimeError, match="OpenCV is not available"):
        manager.acquire("/dev/video0")


def test_shutdown_releases_active_capture(fake_cv2):
    manager = StreamManager()
    cap = manager.acquire("/dev/video0")
    manager.shutdown()
    assert cap.released is True
    snap = manager.status()
    assert snap["refcount"] == 0
    assert snap["active_id"] is None


def test_shutdown_is_idempotent(fake_cv2):
    manager = StreamManager()
    manager.acquire("/dev/video0")
    manager.shutdown()
    manager.shutdown()  # second call must not raise


# ---------------------------------------------------------------------- #
# status / mark_frame                                                     #
# ---------------------------------------------------------------------- #


def test_status_initial_state_is_idle():
    """A fresh manager reports idle and no timestamps."""
    manager = StreamManager()
    snap = manager.status()
    assert snap == {
        "running": False,
        "active_id": None,
        "refcount": 0,
        "last_frame_at": None,
    }


def test_mark_frame_records_timestamp(fake_cv2):
    manager = StreamManager()
    manager.acquire("/dev/video0")
    manager.mark_frame()
    snap = manager.status()
    assert snap["last_frame_at"] is not None
    # ISO-8601 string contains a T separator between date and time.
    assert "T" in snap["last_frame_at"]


def test_failed_open_records_cooldown(fake_cv2):
    """A failed acquire should arm the cooldown for that camera_id."""
    fake_cv2.VideoCapture = lambda source, backend_api=None: _RefusingCapture(source)
    manager = StreamManager()
    with pytest.raises(RuntimeError):
        manager.acquire("0")
    # Second request within cooldown must be rejected.
    with pytest.raises(RuntimeError, match="cooldown"):
        manager.acquire("0")


def test_failed_open_records_cooldown(fake_cv2):
    """A failed acquire should arm the cooldown for that camera_id."""
    _FakeCapture.instances.clear()
    original = fake_cv2.VideoCapture
    fake_cv2.VideoCapture = lambda source, backend_api=None: _RefusingCapture(source)
    manager = StreamManager()
    with pytest.raises(RuntimeError):
        manager.acquire("/dev/video0")
    # Second request within cooldown must be rejected.
    with pytest.raises(RuntimeError, match="cooldown"):
        manager.acquire("/dev/video0")
    fake_cv2.VideoCapture = original


def test_mark_failure_arms_cooldown(fake_cv2):
    """``mark_failure`` arms the cooldown for the given camera_id."""
    manager = StreamManager()
    manager.acquire("/dev/video0")
    manager.release("/dev/video0")
    manager.mark_failure("/dev/video0")
    # Next request within cooldown must be rejected.
    with pytest.raises(RuntimeError, match="cooldown"):
        manager.acquire("/dev/video0")


def test_cooldown_is_per_camera(fake_cv2):
    """Cooldown on one camera must not block other cameras."""
    _FakeCapture.instances.clear()
    original = fake_cv2.VideoCapture
    fake_cv2.VideoCapture = lambda source, backend_api=None: _RefusingCapture(source)
    manager = StreamManager()
    with pytest.raises(RuntimeError):
        manager.acquire("/dev/video0")
    # ``/dev/video1`` has no cooldown, so this should also raise
    # ``RuntimeError`` — but for ``Cannot open``, not ``cooldown``.
    with pytest.raises(RuntimeError, match="Cannot open"):
        manager.acquire("/dev/video1")
    fake_cv2.VideoCapture = original


def test_concurrent_acquire_release_is_safe(fake_cv2):
    """Hammering acquire/release from multiple threads must not crash.

    This is a smoke test — the contract (refcount == 0 at the end,
    capture released) is the only assertion. Race conditions in the
    lock-protected code paths would surface as AssertionError or
    RuntimeError here.
    """
    manager = StreamManager()
    errors: List[BaseException] = []

    def _worker():
        try:
            for _ in range(50):
                manager.acquire("/dev/video0")
                manager.release("/dev/video0")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert errors == []
    snap = manager.status()
    assert snap["refcount"] == 0
    assert snap["active_id"] is None