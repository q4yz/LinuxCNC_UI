"""Tests for the USB camera detection utility.

The detection logic is the most platform-dependent code in the
camera module — these tests pin down behaviour on the host sandbox
(no cameras attached) and exercise the v4l2-ctl parser with
synthetic output so we have coverage even when v4l2-ctl is not on
the CI image.
"""
from __future__ import annotations

import logging
from typing import List

import pytest

from modules.camera.detection import (
    USBDeviceInfo,
    _parse_v4l2ctl_output,
    detect_usb_cameras,
)


# ---------------------------------------------------------------------- #
# detect_usb_cameras — host-aware behaviour                                #
# ---------------------------------------------------------------------- #


def test_detect_returns_list_on_no_cameras():
    """``detect_usb_cameras`` always returns a list (never raises).

    On the CI sandbox no cameras are attached, but the function
    must still return a list with a deterministic shape.
    """
    result = detect_usb_cameras()
    assert isinstance(result, list)
    for entry in result:
        assert isinstance(entry, USBDeviceInfo)
        # ``id`` is always non-empty; either a ``/dev/videoN`` path
        # on Linux or a numeric string on Windows.
        assert entry.id
        assert entry.name
        assert entry.index >= 0


def test_detect_never_raises_even_if_glob_explodes(monkeypatch, caplog):
    """Detection must swallow internal exceptions and log them."""
    import modules.camera.detection as detection

    def _explode(_pattern: str) -> List[str]:  # noqa: D401 - test stub
        raise OSError("synthetic glob failure")

    monkeypatch.setattr(detection, "_list_video_device_paths", _explode)
    with caplog.at_level(logging.WARNING, logger="backend.modules.camera.detection"):
        result = detect_usb_cameras()
    # The exception is caught; an empty list is returned.
    assert result == []


def test_usb_device_info_round_trip():
    """The DTO serialises to a dict matching the OpenAPI shape."""
    entry = USBDeviceInfo(id="/dev/video0", name="HD Webcam", index=0)
    assert entry.to_dict() == {
        "id": "/dev/video0",
        "name": "HD Webcam",
        "index": 0,
    }


# ---------------------------------------------------------------------- #
# v4l2-ctl output parser                                                  #
# ---------------------------------------------------------------------- #


def test_parse_v4l2ctl_output_empty():
    """Empty stdout returns an empty mapping."""
    assert _parse_v4l2ctl_output("", ["/dev/video0"]) == {}


def test_parse_v4l2ctl_output_single_card():
    """Two devices under one card both resolve to the card name."""
    sample = (
        "HD Webcam (usb-0000:00:14.0-1):\n"
        "\t/dev/video0\n"
        "\t/dev/video1\n"
        "\n"
    )
    paths = ["/dev/video0", "/dev/video1"]
    result = _parse_v4l2ctl_output(sample, paths)
    assert result == {
        "/dev/video0": "HD Webcam (usb-0000:00:14.0-1)",
        "/dev/video1": "HD Webcam (usb-0000:00:14.0-1)",
    }


def test_parse_v4l2ctl_output_multiple_cards():
    """Multiple cards produce distinct name entries per device."""
    sample = (
        "HD Webcam (usb-0000:00:14.0-1):\n"
        "\t/dev/video0\n"
        "\n"
        "Other Camera (usb-0000:00:14.0-2):\n"
        "\t/dev/video2\n"
        "\n"
    )
    paths = ["/dev/video0", "/dev/video2"]
    result = _parse_v4l2ctl_output(sample, paths)
    assert result == {
        "/dev/video0": "HD Webcam (usb-0000:00:14.0-1)",
        "/dev/video2": "Other Camera (usb-0000:00:14.0-2)",
    }


def test_parse_v4l2ctl_output_filters_unknown_paths():
    """Devices not in the passed-in path list are ignored."""
    sample = (
        "HD Webcam (usb-0000:00:14.0-1):\n"
        "\t/dev/video0\n"
        "\t/dev/video1\n"
    )
    # /dev/video1 is omitted from the input — should be filtered out.
    paths = ["/dev/video0"]
    result = _parse_v4l2ctl_output(sample, paths)
    assert result == {"/dev/video0": "HD Webcam (usb-0000:00:14.0-1)"}


def test_parse_v4l2ctl_output_handles_crlf_and_extras():
    """Stray whitespace, blank lines, and metadata siblings are tolerated."""
    sample = (
        "\n"
        "HD Webcam (usb-0000:00:14.0-1):\n"
        "        /dev/video0\n"
        "        /dev/video1\n"
        "        /dev/video2\n"
        "\n"
        "\n"
    )
    paths = ["/dev/video0", "/dev/video1", "/dev/video2"]
    result = _parse_v4l2ctl_output(sample, paths)
    assert result == {
        "/dev/video0": "HD Webcam (usb-0000:00:14.0-1)",
        "/dev/video1": "HD Webcam (usb-0000:00:14.0-1)",
        "/dev/video2": "HD Webcam (usb-0000:00:14.0-1)",
    }


def test_parse_v4l2ctl_output_skips_continuation_without_header():
    """A device line without a preceding card header is ignored."""
    sample = (
        "\t/dev/video0\n"  # No card header above
        "HD Webcam (usb-0000:00:14.0-1):\n"
        "\t/dev/video1\n"
    )
    paths = ["/dev/video0", "/dev/video1"]
    result = _parse_v4l2ctl_output(sample, paths)
    assert result == {"/dev/video1": "HD Webcam (usb-0000:00:14.0-1)"}


@pytest.mark.parametrize(
    "line",
    [
        "HD Webcam (usb-0000:00:14.0-1):",
        "HD Webcam (usb-0000:00:14.0-1) :",
        "HD Webcam (usb-0000:00:14.0-1) :  ",  # trailing whitespace
    ],
)
def test_parse_v4l2ctl_output_strips_card_colon(line):
    """Trailing colons (with optional whitespace) are stripped from names."""
    sample = f"{line}\n\t/dev/video0\n"
    result = _parse_v4l2ctl_output(sample, ["/dev/video0"])
    assert result == {"/dev/video0": "HD Webcam (usb-0000:00:14.0-1)"}


# ---------------------------------------------------------------------- #
# Linux detection — fake /dev/video*                                      #
# ---------------------------------------------------------------------- #


def test_linux_detection_with_synthetic_devices(monkeypatch, tmp_path):
    """Inject a ``/dev/video*`` path and a v4l2-ctl name; verify the row."""
    import modules.camera.detection as detection

    fake_path = str(tmp_path / "video0")
    monkeypatch.setattr(
        detection,
        "_list_video_device_paths",
        lambda: [fake_path],
    )
    monkeypatch.setattr(
        detection,
        "_query_v4l2_names",
        lambda _paths: {fake_path: "Synthetic Cam"},
    )

    result = detection._detect_linux()
    assert len(result) == 1
    assert result[0].id == fake_path
    assert result[0].name == "Synthetic Cam"
    assert result[0].index == 0


def test_linux_detection_falls_back_when_v4l2ctl_missing(monkeypatch):
    """When v4l2-ctl returns no names the OpenCV probe takes over."""
    import modules.camera.detection as detection

    monkeypatch.setattr(detection, "_list_video_device_paths", lambda: ["/dev/video0"])
    monkeypatch.setattr(detection, "_query_v4l2_names", lambda _paths: {})

    # Stub out the OpenCV probe so the test does not need a real camera.
    monkeypatch.setattr(
        detection,
        "_probe_with_opencv",
        lambda _path, index: f"USB Camera {index}",
    )

    result = detection._detect_linux()
    assert len(result) == 1
    assert result[0].id == "/dev/video0"
    assert result[0].name == "USB Camera 0"