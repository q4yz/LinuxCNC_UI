"""Linux-first USB camera detection utility.

The camera module must list the actual hardware available on the host so
the Vue frontend can render a meaningful picker (rather than guessing
indices). This module is the single source of truth for that list.

Platform behaviour:

* **Linux (production target)**
    1. Enumerate ``/dev/video*`` via :mod:`glob`.
    2. Ask each node what it is (``VIDIOC_QUERYCAP``) and keep only
       real capture devices. Not every node is a camera: on the BTT
       CB1's Allwinner H616 ``/dev/video0`` is ``cedrus``, the hardware
       video decoder (memory-to-memory), and a UVC webcam brings a
       second, metadata-only node. ``QUERYCAP`` only reads the driver's
       capability flags — it does not start or claim a stream, so it
       never races ustreamer.
    3. Name: the card name from ``QUERYCAP``, else
       ``v4l2-ctl --list-devices``, else a synthetic ``"USB Camera N"``.
    4. Id: the stable ``/dev/v4l/by-id/...`` link of the node (else
       ``/dev/v4l/by-path/...``, else ``/dev/videoN``) — ``N`` can change
       between boots or replugs, the by-id name does not. A saved
       ``/dev/videoN`` still resolves through :func:`resolve_device_id`.

* **Windows / macOS / other**
    Return an empty list. The camera module is Linux-only because
    ``ustreamer`` is Linux-only; the operator-facing empty state
    surfaces the reason through the ``streamMessage`` field on
    ``GET /api/v1/modules/camera/status``. The frontend renders that
    message verbatim so operators on Windows see a "this is not
    supported on this platform" hint rather than a silently-broken
    camera panel.

The module never raises. ``v4l2-ctl`` missing, no cameras attached,
or any other internal failure degrades to an empty list (with a log
entry). The endpoint that consumes this list (``GET /devices``)
serves the result verbatim.
"""
from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import struct
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

try:  # Linux only (V4L2 ioctl); Windows has no fcntl and no /dev/video*.
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None

logger = logging.getLogger("backend.services.camera_detection")

# Cap on the ``v4l2-ctl`` call so a hung driver cannot stall the
# endpoint for more than two seconds.
_V4L2_LIST_TIMEOUT_S = 2.0


# ---------------------------------------------------------------------- #
# Public data model                                                       #
# ---------------------------------------------------------------------- #


class USBDeviceInfo:
    """Lightweight DTO describing one detected USB camera.

    Kept as a plain class so the FastAPI router can serialise it
    directly (the OpenAPI schema is generated from the field docstrings
    via :func:`_to_payload_dict`).
    """

    __slots__ = ("id", "name", "index")

    def __init__(self, id: str, name: str, index: int) -> None:
        self.id = id
        self.name = name
        self.index = index

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"USBDeviceInfo(id={self.id!r}, name={self.name!r}, index={self.index!r})"

    def to_dict(self) -> Dict[str, object]:
        return {"id": self.id, "name": self.name, "index": self.index}


# ---------------------------------------------------------------------- #
# Public entry point                                                      #
# ---------------------------------------------------------------------- #


def detect_usb_cameras() -> List[USBDeviceInfo]:
    """Return every USB camera the host currently exposes.

    The returned list is sorted by ascending ``index`` so the frontend
    picker sees a stable order. ``index`` is the V4L2 integer index
    (``0`` for ``/dev/video0``, ``1`` for ``/dev/video1`` …). On
    non-Linux platforms the function returns an empty list and the
    supervisor's diagnostic message carries the explanation.

    The function never raises. All platform-specific errors are caught
    and logged at WARNING so a misconfigured host still boots the
    backend.
    """
    try:
        if sys.platform.startswith("linux"):
            return _detect_linux()
        logger.info("USB camera detection skipped on platform=%s", sys.platform)
        return []
    except Exception as exc:  # noqa: BLE001 - defensive: never crash boot
        logger.warning("USB camera detection failed: %s", exc)
        return []


# ---------------------------------------------------------------------- #
# Linux                                                                   #
# ---------------------------------------------------------------------- #


def _detect_linux() -> List[USBDeviceInfo]:
    """Linux detection: capture-capable ``/dev/video*`` nodes, by stable id."""
    paths = _list_video_device_paths()
    if not paths:
        logger.info("No /dev/video* devices found.")
        return []

    capture_paths: List[str] = []
    card_names: Dict[str, str] = {}
    for path in paths:
        caps = _query_capabilities(path)
        if caps is None:
            # Could not ask (no permission, odd driver): keep the node,
            # the supervisor reports whether ustreamer can open it.
            capture_paths.append(path)
            continue
        card, device_caps = caps
        if not _is_capture_device(device_caps):
            logger.info("Skipping %s (%s): not a video capture device.", path, card or "?")
            continue
        capture_paths.append(path)
        if card:
            card_names[path] = card
    if not capture_paths:
        logger.info("No video capture devices among %s.", ", ".join(paths))
        return []

    missing = [p for p in capture_paths if p not in card_names]
    names_by_path = {**(_query_v4l2_names(missing) if missing else {}), **card_names}
    stable = _stable_links()

    devices: List[USBDeviceInfo] = []
    for index, path in enumerate(capture_paths):
        name = names_by_path.get(path)
        if name is None:
            # No name from the driver or v4l2-ctl. Fall back to a
            # synthetic one so the picker still surfaces the device.
            name = f"USB Camera {index}"
        device_id = stable.get(os.path.realpath(path), path)
        devices.append(USBDeviceInfo(id=device_id, name=name, index=index))

    logger.info("Detected %d USB camera(s) on Linux.", len(devices))
    return devices


def resolve_device_id(camera_id: Optional[str]) -> Optional[str]:
    """Map a saved camera id onto the id :func:`detect_usb_cameras` uses.

    A ``/dev/videoN`` (what older versions stored) or any other link to
    the same node resolves to that camera's stable id; URLs and unknown
    ids come back unchanged.
    """
    if not camera_id or "://" in camera_id:
        return camera_id
    target = os.path.realpath(camera_id)
    for device in detect_usb_cameras():
        if device.id == camera_id or os.path.realpath(device.id) == target:
            return device.id
    return camera_id


# ---------------------------------------------------------------------- #
# V4L2 capabilities                                                       #
# ---------------------------------------------------------------------- #

# struct v4l2_capability: driver[16] card[32] bus_info[32] version
# capabilities device_caps reserved[3] — 104 bytes.
_V4L2_CAPABILITY = struct.Struct("16s32s32sIII3I")
# _IOR('V', 0, struct v4l2_capability)
_VIDIOC_QUERYCAP = (2 << 30) | (_V4L2_CAPABILITY.size << 16) | (ord("V") << 8) | 0
_CAP_VIDEO_CAPTURE = 0x00000001
_CAP_VIDEO_CAPTURE_MPLANE = 0x00001000
_CAP_VIDEO_M2M_MPLANE = 0x00004000
_CAP_VIDEO_M2M = 0x00008000
_CAP_DEVICE_CAPS = 0x80000000


def _query_capabilities(path: str) -> Optional[Tuple[str, int]]:
    """``(card name, device caps)`` of one node via ``VIDIOC_QUERYCAP``,
    or ``None`` when the node cannot be asked."""
    if fcntl is None:
        return None
    try:
        fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        buf = bytearray(_V4L2_CAPABILITY.size)
        fcntl.ioctl(fd, _VIDIOC_QUERYCAP, buf)
    except OSError:
        return None
    finally:
        os.close(fd)
    _driver, card, _bus, _version, caps, device_caps, *_ = _V4L2_CAPABILITY.unpack(bytes(buf))
    if not caps & _CAP_DEVICE_CAPS:
        device_caps = caps
    return card.split(b"\0", 1)[0].decode("utf-8", "replace").strip(), device_caps


def _is_capture_device(device_caps: int) -> bool:
    """A camera: video capture, and not a memory-to-memory codec (which
    also reports capture). Metadata-only nodes report neither."""
    if device_caps & (_CAP_VIDEO_M2M | _CAP_VIDEO_M2M_MPLANE):
        return False
    return bool(device_caps & (_CAP_VIDEO_CAPTURE | _CAP_VIDEO_CAPTURE_MPLANE))


#: udev's stable camera links, best first.
_STABLE_LINK_DIRS = ("/dev/v4l/by-id", "/dev/v4l/by-path")


def _stable_links() -> Dict[str, str]:
    """``{real /dev/videoN: stable link}`` — ``/dev/v4l/by-id`` first,
    ``/dev/v4l/by-path`` for a camera without a serial-style id."""
    links: Dict[str, str] = {}
    for folder in _STABLE_LINK_DIRS:
        try:
            entries = sorted(glob.glob(os.path.join(folder, "*")))
        except Exception:  # noqa: BLE001 - glob can be sandboxed
            continue
        for link in entries:
            links.setdefault(os.path.realpath(link), link)
    return links


def _list_video_device_paths() -> List[str]:
    """Enumerate ``/dev/video*`` paths, sorted ascending by index."""
    try:
        paths = sorted(glob.glob("/dev/video*"), key=_video_number)
    except Exception as exc:  # noqa: BLE001 - glob can be sandboxed
        logger.warning("glob('/dev/video*') failed: %s", exc)
        return []
    # Metadata nodes and codecs are dropped later, by their V4L2
    # capabilities (``_is_capture_device``).
    return [p for p in paths if os.path.exists(p)]


def _video_number(path: str) -> Tuple[int, str]:
    """Sort key: ``/dev/video2`` before ``/dev/video10``."""
    match = re.search(r"(\d+)$", path)
    return (int(match.group(1)) if match else -1, path)


# ---------------------------------------------------------------------- #
# v4l2-ctl parsing                                                        #
# ---------------------------------------------------------------------- #


def _query_v4l2_names(paths: List[str]) -> Dict[str, str]:
    """Return a mapping of ``/dev/videoX`` -> card name via v4l2-ctl.

    Returns an empty dict if ``v4l2-ctl`` is unavailable or fails. The
    caller is responsible for the synthetic-name fallback in that case.
    """
    if shutil.which("v4l2-ctl") is None:
        logger.debug("v4l2-ctl not on PATH; skipping name lookup.")
        return {}

    try:
        output = subprocess.check_output(
            ["v4l2-ctl", "--list-devices"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=_V4L2_LIST_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "v4l2-ctl --list-devices timed out after %.1fs", _V4L2_LIST_TIMEOUT_S
        )
        return {}
    except subprocess.CalledProcessError as exc:
        logger.warning(
            "v4l2-ctl --list-devices exited %s: %s",
            exc.returncode,
            exc.output.strip().splitlines()[0] if exc.output else "",
        )
        return {}
    except FileNotFoundError:
        # Race: shutil.which saw it, but the binary disappeared.
        logger.warning("v4l2-ctl disappeared during execution.")
        return {}
    except Exception as exc:  # noqa: BLE001 - defensive
        logger.warning("v4l2-ctl --list-devices raised: %s", exc)
        return {}

    return _parse_v4l2ctl_output(output, paths)


# Regex used to extract the ``/dev/videoN`` tokens out of a single
# v4l2-ctl device block. ``/dev/video`` is followed by 1+ digits so we
# never accidentally match ``/dev/video-meta`` style siblings.
_DEV_VIDEO_RE = re.compile(r"(/dev/video\d+)")


def _parse_v4l2ctl_output(
    output: str, paths: List[str]
) -> Dict[str, str]:
    """Parse ``v4l2-ctl --list-devices`` into ``{path: card_name}``.

    Output format (one block per card)::

        HD Webcam (usb-0000:00:14.0-1):
            /dev/video0
            /dev/video1

        Other Camera (usb-0000:00:14.0-2):
            /dev/video2

    Lines without a leading whitespace continuation belong to the
    *card header*; everything beneath it (until the next blank/header
    line) is the device list for that card.
    """
    valid_paths = set(paths)
    name_by_path: Dict[str, str] = {}

    current_name: Optional[str] = None
    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        if not line:
            # Blank line ends the current card block.
            current_name = None
            continue
        if not line.startswith((" ", "\t")):
            # Card header — strip the trailing colon and any
            # whitespace.
            current_name = line.rstrip(":").strip() or None
            continue
        if current_name is None:
            # Continuation line without a preceding header; ignore.
            continue
        for match in _DEV_VIDEO_RE.finditer(line):
            device_path = match.group(1)
            if device_path in valid_paths and device_path not in name_by_path:
                name_by_path[device_path] = current_name

    return name_by_path


__all__ = ["USBDeviceInfo", "detect_usb_cameras", "resolve_device_id"]
