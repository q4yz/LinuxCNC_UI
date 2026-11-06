"""Camera list on a BTT CB1 (issue #123): only real capture devices,
identified by their stable ``/dev/v4l/by-id`` link."""
from __future__ import annotations

import socket

import pytest

import services.camera.camera_detection as detection
from services.camera.UstreamerSupervisor import UstreamerSupervisor

CAPTURE = detection._CAP_VIDEO_CAPTURE | detection._CAP_DEVICE_CAPS
LIFECAM_ID = "usb-Microsoft_Microsoft_LifeCam_HD-3000-video-index0"


@pytest.fixture
def cb1(monkeypatch, tmp_path):
    """/dev/video0 cedrus (decoder), video1 LifeCam, video2 its metadata."""
    dev = tmp_path / "dev"
    dev.mkdir()
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    paths = [str(dev / f"video{n}") for n in range(3)]
    for path in paths:
        open(path, "w").close()
    (by_id / LIFECAM_ID).symlink_to(paths[1])
    (by_id / LIFECAM_ID.replace("index0", "index1")).symlink_to(paths[2])
    caps = {
        paths[0]: ("cedrus", detection._CAP_VIDEO_M2M_MPLANE | detection._CAP_VIDEO_CAPTURE_MPLANE),
        paths[1]: ("Microsoft LifeCam HD-3000", CAPTURE),
        paths[2]: ("Microsoft LifeCam HD-3000", 0x00800000),  # V4L2_CAP_META_CAPTURE
    }
    monkeypatch.setattr(detection.sys, "platform", "linux")
    monkeypatch.setattr(detection, "_list_video_device_paths", lambda: paths)
    monkeypatch.setattr(detection, "_query_capabilities", caps.get)
    monkeypatch.setattr(detection, "_query_v4l2_names", lambda _p: {})
    monkeypatch.setattr(detection, "_STABLE_LINK_DIRS", (str(by_id),))
    return paths, str(by_id / LIFECAM_ID)


def test_only_the_camera_is_listed_by_its_stable_id(cb1):
    _paths, lifecam = cb1
    devices = detection.detect_usb_cameras()
    assert [(d.id, d.name, d.index) for d in devices] == [(lifecam, "Microsoft LifeCam HD-3000", 0)]


def test_saved_dev_video_path_resolves_to_the_stable_id(cb1):
    paths, lifecam = cb1
    assert detection.resolve_device_id(paths[1]) == lifecam
    assert detection.resolve_device_id(lifecam) == lifecam
    # Not a camera (cedrus), a URL, nothing: unchanged.
    assert detection.resolve_device_id(paths[0]) == paths[0]
    assert detection.resolve_device_id("http://cam/stream") == "http://cam/stream"
    assert detection.resolve_device_id("") == ""


def test_node_that_cannot_be_asked_is_kept(monkeypatch, cb1):
    paths, _lifecam = cb1
    monkeypatch.setattr(detection, "_query_capabilities", lambda _p: None)
    assert [d.id for d in detection.detect_usb_cameras()][0] == paths[0]


@pytest.mark.parametrize(
    ("caps", "is_camera"),
    [
        (detection._CAP_VIDEO_CAPTURE, True),
        (detection._CAP_VIDEO_CAPTURE_MPLANE, True),
        (detection._CAP_VIDEO_M2M, False),
        (detection._CAP_VIDEO_M2M_MPLANE | detection._CAP_VIDEO_CAPTURE_MPLANE, False),
        (0x00800000, False),  # metadata only
        (0, False),
    ],
)
def test_capture_flag(caps, is_camera):
    assert detection._is_capture_device(caps) is is_camera


def test_numeric_device_order():
    paths = ["/dev/video10", "/dev/video2", "/dev/video1"]
    assert sorted(paths, key=detection._video_number) == ["/dev/video1", "/dev/video2", "/dev/video10"]


def test_port_in_use_is_skipped(monkeypatch):
    supervisor = UstreamerSupervisor()
    monkeypatch.setattr(supervisor, "known_device_ids", lambda: ["/dev/v4l/by-id/a", "/dev/v4l/by-id/b"])
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        busy = blocker.getsockname()[1]
        import services.camera.UstreamerSupervisor as module

        monkeypatch.setattr(module, "_USTREAMER_BASE_PORT", busy - 1)
        # "b" (index 1) would get the busy port; it moves to the next one.
        assert supervisor._allocate_port("/dev/v4l/by-id/b") == busy + 1
        # A port another camera of ours holds is skipped too.
        supervisor._ports["/dev/v4l/by-id/a"] = busy + 1
        assert supervisor._allocate_port("/dev/v4l/by-id/b") == busy + 2
