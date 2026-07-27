"""Linux-first USB camera detection utility.

The camera module must list the actual hardware available on the host so
the Vue frontend can render a meaningful picker (rather than guessing
indices). This module is the single source of truth for that list.

Platform behaviour:

* **Linux (production target)**
    1. Enumerate ``/dev/video*`` via :mod:`glob`.
    2. Parse ``v4l2-ctl --list-devices`` to recover the human-readable
       card name for each device path. ``v4l2-ctl`` ships with the
       ``v4l-utils`` package and is the standard way to query V4L2
       metadata without opening the device.
    3. Fall back to OpenCV probing (try ``cv2.VideoCapture``) for any
       device the ``v4l2-ctl`` parse did not resolve. OpenCV will not
       produce a name but can confirm the device opens cleanly.
    4. Last-resort fallback: a synthetic name ``"USB Camera N"`` derived
       from the device path.

* **Windows (developer convenience only)**
    Return indices ``0..MAX_INDEX`` — there is no portable
    ``/dev/video*`` equivalent. OpenCV probing is used so the frontend
    still sees only devices that actually open.

* **Other platforms**
    Return an empty list. The frontend already handles the empty
    state — no error is raised.

The module never raises. ``v4l2-ctl`` missing, ``cv2`` missing, no
cameras attached — all of these degrade to an empty list with a log
entry. The endpoint that consumes this list (``GET /usb``) can serve
the result verbatim.
"""
from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import subprocess
import sys
from typing import Dict, List, Optional

logger = logging.getLogger("backend.modules.camera.detection")

# Cap the Windows index probe so a misconfigured dev box does not spend
# minutes opening phantom devices. Four cameras is plenty for local dev.
_WINDOWS_MAX_INDEX = 3

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
    picker sees a stable order. ``index`` is the OpenCV integer index
    (``0`` for ``/dev/video0``, ``1`` for ``/dev/video1`` …) and doubles
    as a fallback identifier when ``/dev/video*`` paths are unavailable
    (e.g. on Windows).

    The function never raises. All platform-specific errors are caught
    and logged at WARNING so a misconfigured host still boots the
    backend.
    """
    try:
        if sys.platform.startswith("linux"):
            return _detect_linux()
        if sys.platform == "win32":
            return _detect_windows()
        logger.info("USB camera detection skipped on platform=%s", sys.platform)
        return []
    except Exception as exc:  # noqa: BLE001 - defensive: never crash boot
        logger.warning("USB camera detection failed: %s", exc)
        return []


# ---------------------------------------------------------------------- #
# Linux                                                                   #
# ---------------------------------------------------------------------- #


def _detect_linux() -> List[USBDeviceInfo]:
    """Linux detection: ``/dev/video*`` + ``v4l2-ctl --list-devices``."""
    paths = _list_video_device_paths()
    if not paths:
        logger.info("No /dev/video* devices found.")
        return []

    names_by_path = _query_v4l2_names(paths)

    devices: List[USBDeviceInfo] = []
    for index, path in enumerate(paths):
        name = names_by_path.get(path)
        if name is None:
            # Last-ditch: ask OpenCV whether the device opens. If it
            # does, fall back to a synthetic name so the picker still
            # surfaces the device.
            name = _probe_with_opencv(path, index)
        if name is None:
            logger.info(
                "Skipping %s: cannot resolve human-readable name.", path
            )
            continue
        devices.append(USBDeviceInfo(id=path, name=name, index=index))

    devices.sort(key=lambda d: d.index)
    logger.info("Detected %d USB camera(s) on Linux.", len(devices))
    return devices


def _list_video_device_paths() -> List[str]:
    """Enumerate ``/dev/video*`` paths, sorted ascending by index."""
    try:
        paths = sorted(glob.glob("/dev/video*"))
    except Exception as exc:  # noqa: BLE001 - glob can be sandboxed
        logger.warning("glob('/dev/video*') failed: %s", exc)
        return []
    # Filter out metadata siblings (``/dev/video10`` is typically a
    # metadata node on some UVC drivers and does not carry a frame
    # stream). ``v4l2-ctl --list-devices`` reports these as well, so
    # letting them through is fine — the loop in ``_detect_linux``
    # will skip entries we can't resolve.
    return [p for p in paths if os.path.exists(p)]


# ---------------------------------------------------------------------- #
# v4l2-ctl parsing                                                        #
# ---------------------------------------------------------------------- #


def _query_v4l2_names(paths: List[str]) -> Dict[str, str]:
    """Return a mapping of ``/dev/videoX`` -> card name via v4l2-ctl.

    Returns an empty dict if ``v4l2-ctl`` is unavailable or fails. The
    caller is responsible for fallback probing in that case.
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


# ---------------------------------------------------------------------- #
# OpenCV probe fallback                                                   #
# ---------------------------------------------------------------------- #


def _probe_with_opencv(path: str, index: int) -> Optional[str]:
    """Try to open ``path`` with OpenCV as a last-resort name source.

    Returns a synthetic name ``"USB Camera N"`` if the device opens
    cleanly so the picker surfaces it. Returns ``None`` if OpenCV is
    unavailable or the device cannot be opened.
    """
    try:
        import cv2  # type: ignore  # local import — module is optional
    except Exception:  # noqa: BLE001 - cv2 may be missing in CI
        return None

    cap = None
    try:
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return None
        return f"USB Camera {index}"
    except Exception as exc:  # noqa: BLE001 - cv2 internals vary
        logger.debug("OpenCV probe for %s failed: %s", path, exc)
        return None
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------- #
# Windows                                                                 #
# ---------------------------------------------------------------------- #


def _detect_windows() -> List[USBDeviceInfo]:
    """Return synthetic ``/dev/videoN``-style entries for Windows.

    OpenCV does not expose a portable device-listing API on Windows,
    so we probe the first ``_WINDOWS_MAX_INDEX + 1`` indices. Devices
    that fail to open are filtered out so the frontend never sees a
    dead picker entry. The ``id`` field is the integer index (since
    there is no ``/dev/video*`` equivalent); the frontend stores this
    verbatim and the streaming endpoint will accept it back as the
    ``id`` query parameter.
    """
    try:
        import cv2  # type: ignore
    except Exception:  # noqa: BLE001 - cv2 may be missing
        logger.info("OpenCV not available; returning empty Windows list.")
        return []

    devices: List[USBDeviceInfo] = []
    for index in range(_WINDOWS_MAX_INDEX + 1):
        cap = None
        try:
            cap = cv2.VideoCapture(index)
            if cap.isOpened():
                devices.append(
                    USBDeviceInfo(
                        id=str(index),
                        name=f"USB Camera {index}",
                        index=index,
                    )
                )
        except Exception as exc:  # noqa: BLE001 - cv2 internals vary
            logger.debug("Windows probe for index %d failed: %s", index, exc)
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:  # noqa: BLE001
                    pass

    devices.sort(key=lambda d: d.index)
    logger.info("Detected %d USB camera(s) on Windows.", len(devices))
    return devices


__all__ = ["USBDeviceInfo", "detect_usb_cameras"]