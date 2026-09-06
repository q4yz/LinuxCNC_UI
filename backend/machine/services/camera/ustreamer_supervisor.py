"""``UstreamerSupervisor`` — one ``ustreamer`` subprocess per camera.

Extracted from ``routers/camera.py`` (see that module's docstring for
the architecture rationale — ustreamer over OpenCV). The camera
module doesn't fit the Router → Service → DTO → Mapper → Storage
split used elsewhere in the codebase: there is no domain data to map,
just a process to supervise and bytes to proxy. Splitting along that
line here would be ceremony, not clarity. What genuinely helps
readability instead is a plain **process-boundary split** — this file
owns subprocess lifecycle and diagnostics; ``routers/camera.py`` owns
HTTP endpoints and stream proxying — so each file has one job and
neither reads like two modules stapled together.

Router precedent: ``services/camera/camera_mjpeg_proxy.py`` and
``services/camera/shared_mjpeg_proxy.py`` already live under this
same ``services/camera/`` package; this file completes that layout.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from services.camera.camera_detection import detect_usb_cameras
from models.camera_settings import CameraSettings

logger = logging.getLogger("backend.camera_service")


# Port allocation strategy: one ustreamer per detected device, starting
# at 8080 + index. The supervisor persists the actual port alongside
# the device id in its in-process map; the mapping is stable for the
# lifetime of the backend process. Operators that need to bookmark a
# stream URL can rely on the port staying put until the backend
# restarts.
_USTREAMER_BASE_PORT = 8080


class UstreamerSupervisor:
    """One ``ustreamer`` subprocess per ``/dev/videoN`` device.

    The supervisor owns:

    * the per-device subprocess table (``_procs``: id -> Popen);
    * the device → port mapping (``_ports``);
    * a per-device cooldown (``_cooldown_until``) so a freshly-failed
      device is not hammered by the frontend's exponential backoff;
    * the diagnostic ``message`` returned to the frontend via
      ``status()`` and the ``/stream`` 503 body.

    Thread-safety
    -------------
    Public methods (``spawn_or_reuse``, ``stop``, ``shutdown``,
    ``status``, ``read_default_device_id``, ``read_ip_camera_url``)
    take :attr:`_lock` so concurrent FastAPI threadpool tasks cannot
    tear a child down twice.

    Why not just a module-level capture?
    ------------------------------------
    The supervisor spawns one ``ustreamer`` per id the first time a
    client requests ``/stream?id=...``. The child stays alive until
    the operator switches cameras or the backend shuts down. Unlike
    the OpenCV-era design there is no per-frame loop on the Python
    side; the child owns the capture / encode cycle entirely.
    """

    # ustreamer flags we always pass. Resolution / framerate / encoder
    # quality are not user-tunable from the settings panel — they live
    # here as constants and would only move to settings if a future
    # ticket adds a "stream quality" selector.
    _USTREAMER_ARGS = (
        "-m",  # MJPEG output
        "JPEG",
        "-r", "640x480",  # resolution
        "-f", "30",  # framerate cap
        "--allow-origin", "*",  # CORS for browser <img> tags
    )

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # id → ``subprocess.Popen`` handle.
        self._procs: Dict[str, "subprocess.Popen[bytes]"] = {}
        # id → assigned TCP port.
        self._ports: Dict[str, int] = {}
        # id → next-eligible ``datetime`` after which retries are
        # allowed. Mirrors the OpenCV-era cooldown so the frontend's
        # exponential backoff does not pile requests on a freshly-
        # crashed device.
        self._cooldown_until: Dict[str, datetime] = {}
        self._cooldown_seconds = 5.0
        self._settings_store = None  # late-bound by bind_settings

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    def bind_settings(self, settings_store) -> None:
        """Attach the module's SettingsStore. Idempotent."""
        self._settings_store = settings_store

    def shutdown(self) -> None:
        """Terminate every spawned child. Idempotent."""
        with self._lock:
            for camera_id in list(self._procs.keys()):
                self._terminate_locked(camera_id)

    # ------------------------------------------------------------------ #
    # Settings passthrough                                                #
    # ------------------------------------------------------------------ #

    def _load_settings(self) -> CameraSettings:
        """Read the merged settings; fall back to defaults on error.

        Mirrors the legacy ``StreamManager.reload_config`` shape so a
        malformed PUT never crashes the streaming path.
        """
        try:
            if self._settings_store is None:
                return CameraSettings()
            payload = self._settings_store.read_all()
            return CameraSettings(**payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "UstreamerSupervisor: invalid settings payload (%s); "
                "using defaults",
                exc,
            )
            return CameraSettings()

    def read_default_device_id(self) -> Optional[str]:
        """Return the configured ``default_device_id`` (or ``None``)."""
        value = getattr(self._load_settings(), "default_device_id", "")
        return value or None

    def read_ip_camera_url(self) -> Optional[str]:
        """Return the configured ``ip_camera_url`` (or ``None``)."""
        value = getattr(self._load_settings(), "ip_camera_url", "")
        return value or None

    # ------------------------------------------------------------------ #
    # Device discovery                                                   #
    # ------------------------------------------------------------------ #

    def known_device_ids(self) -> List[str]:
        """Return the ``/dev/video*`` paths the detection layer found.

        The supervisor treats ``known_device_ids`` as the authoritative
        list when an explicit ``/stream?id=...`` request asks for a
        device that was not enumerated. Anything outside this list
        still gets a fallback diagnostic but is treated as missing.
        """
        return [device.id for device in detect_usb_cameras()]

    # ------------------------------------------------------------------ #
    # Spawn / Stop                                                       #
    # ------------------------------------------------------------------ #

    def spawn_or_reuse(self, camera_id: str) -> Dict[str, str]:
        """Return ``{"id": ..., "url": ...}`` for ``camera_id``.

        Spawns the child if it is not already running. Raises
        :class:`RuntimeError` if the spawn fails — callers should
        translate that into an actionable HTTP error.

        HTTP / HTTPS / RTSP URLs are a special case: ``ustreamer``
        cannot consume them, so the supervisor serves them by
        returning the URL itself. The ``/stream`` endpoint feeds that
        URL to the MJPEG fan-out proxy, which streams the upstream
        bytes back same-origin. No subprocess is spawned, no
        ``/dev/videoN`` device is needed, and the dependency
        checks (ustreamer on PATH, Linux platform, …) do not
        apply. This is what lets operators paste an arbitrary IP
        camera URL into the Settings panel and have it Just Work.
        """
        if not camera_id:
            raise RuntimeError("camera_id is required")

        with self._lock:
            # IP camera passthrough: the proxy fetches the upstream
            # server-side, so the supervisor has no subprocess to
            # manage. Returning the URL verbatim also means an
            # upstream URL with embedded credentials
            # (``http://user:pass@host/path``) is preserved as-is
            # (the proxy converts userinfo into an Authorization
            # header).
            if camera_id.startswith(("http://", "https://", "rtsp://")):
                return {"id": camera_id, "url": camera_id}

            cooldown_until = self._cooldown_until.get(camera_id)
            if cooldown_until is not None:
                now = datetime.now(timezone.utc)
                if now < cooldown_until:
                    remaining = (cooldown_until - now).total_seconds()
                    raise RuntimeError(
                        f"Camera {camera_id!r} is in cooldown "
                        f"({remaining:.1f}s remaining)"
                    )
                del self._cooldown_until[camera_id]

            proc = self._procs.get(camera_id)
            if proc is not None and proc.poll() is None:
                # Still alive — reuse.
                port = self._ports[camera_id]
                return {"id": camera_id, "url": self._stream_url(port)}

            # Either no child or it has exited. (Re)spawn.
            try:
                port = self._ports[camera_id]
            except KeyError:
                port = self._allocate_port(camera_id)
                self._ports[camera_id] = port

            proc = self._spawn_locked(camera_id, port)
            self._procs[camera_id] = proc
            logger.info(
                "UstreamerSupervisor: spawned ustreamer id=%s port=%d (pid=%d)",
                camera_id,
                port,
                proc.pid,
            )
            return {"id": camera_id, "url": self._stream_url(port)}

    def stop(self, camera_id: str) -> None:
        """Terminate the child for ``camera_id`` if any. Idempotent."""
        with self._lock:
            self._terminate_locked(camera_id)

    # ------------------------------------------------------------------ #
    # Status / diagnostic                                                 #
    # ------------------------------------------------------------------ #

    def status(self) -> Dict[str, object]:
        """Return the JSON payload for ``GET /status``.

        Always returns ``running`` as a boolean; ``message`` is empty
        when ``running`` is True and otherwise carries a single-line
        operator hint explaining what is missing.
        """
        with self._lock:
            active_id = self.read_default_device_id()

            # Pre-flight diagnostic checks (cheap; no subprocess I/O).
            message = self._diagnostic_message_locked(active_id)
            if message:
                return {
                    "running": False,
                    "active_id": active_id,
                    "ustreamer_url": None,
                    "message": message,
                }

            # No id configured — operator has not picked a device yet.
            if not active_id:
                return {
                    "running": False,
                    "active_id": None,
                    "ustreamer_url": None,
                    "message": "",
                }

            # IP camera passthrough: the supervisor never spawns a
            # subprocess for HTTP / HTTPS sources, so the absence of
            # a child entry is the normal case rather than a failure.
            # The ``/stream`` endpoint proxies these via the MJPEG
            # proxy module (credentials stay server-side — the
            # browser never sees the upstream URL); ``status()``
            # reports ``running=True`` so the operator's UI does not
            # render a confusing "no camera" placeholder.
            if active_id.startswith(("http://", "https://")):
                return {
                    "running": True,
                    "active_id": active_id,
                    "ustreamer_url": active_id,
                    "message": "",
                }

            proc = self._procs.get(active_id)
            if proc is None or proc.poll() is not None:
                # Child not running or has exited. Operator needs to
                # know whether the problem is ustreamer itself or
                # something downstream (port already bound, device
                # busy, etc.).
                if proc is not None:
                    code = proc.returncode
                    self._cooldown_until[active_id] = (
                        datetime.now(timezone.utc)
                        + timedelta(seconds=self._cooldown_seconds)
                    )
                    self._procs.pop(active_id, None)
                    return {
                        "running": False,
                        "active_id": active_id,
                        "ustreamer_url": None,
                        "message": (
                            f"ustreamer exited unexpectedly "
                            f"(code {code}). Check the backend logs "
                            f"for details."
                        ),
                    }
                # No child has been spawned yet — tell the operator to
                # click the camera (which fires the first /stream).
                return {
                    "running": False,
                    "active_id": active_id,
                    "ustreamer_url": None,
                    "message": "",
                }

            port = self._ports.get(active_id)
            return {
                "running": True,
                "active_id": active_id,
                "ustreamer_url": self._stream_url(port) if port else None,
                "message": "",
            }

    def _diagnostic_message_locked(self, camera_id: Optional[str]) -> str:
        """Return a one-line operator hint, or ``""`` if everything is fine.

        Caller must hold :attr:`_lock`. Resolution order:

        1. RTSP URL → not supported (the proxy module handles HTTP /
           HTTPS only; RTSP would need ffmpeg or gst-launch to
           transcode into MJPEG, which is out of scope).
        2. HTTP / HTTPS URL → empty (the proxy module handles every
           other concern — credentials, network errors, upstream
           auth failures — itself and surfaces them as 503s).
        3. Non-Linux platform → dependency message (ustreamer is
           Linux-only).
        4. ``ustreamer`` binary missing on PATH.
        5. ``camera_id`` provided but not present in ``/dev/video*``.
        6. No devices and no IP camera configured.
        """
        if camera_id and camera_id.startswith("rtsp://"):
            return (
                "RTSP camera URLs are not supported by the IP-camera "
                "proxy. The backend can consume HTTP / HTTPS MJPEG "
                "streams only; converting RTSP to MJPEG requires "
                "ffmpeg or gst-launch and is out of scope."
            )

        if camera_id and camera_id.startswith(("http://", "https://")):
            return ""

        if not sys.platform.startswith("linux"):
            return (
                "The camera module requires Linux; ustreamer does not "
                "run on this platform."
            )

        if shutil.which("ustreamer") is None:
            return (
                "ustreamer is not installed on this host. Run "
                "'sudo apt install ustreamer' on the LinuxCNC controller."
            )

        known = self.known_device_ids()
        if camera_id and camera_id not in known:
            return (
                f"Camera {camera_id} is not present. Reconnect the "
                f"camera or pick another device."
            )

        if not known and not self.read_ip_camera_url():
            return (
                "No USB cameras detected and no IP camera configured. "
                "Plug in a camera or save an IP camera URL."
            )

        return ""

    # ------------------------------------------------------------------ #
    # Subprocess plumbing                                                 #
    # ------------------------------------------------------------------ #

    def _allocate_port(self, camera_id: str) -> int:
        """Pick a TCP port for ``camera_id``.

        Strategy: index by enumeration order, so ``/dev/video0`` →
        8080, ``/dev/video1`` → 8081, … The operator can therefore
        bookmark a single camera and have the URL stay stable across
        restarts as long as the device order is preserved.
        """
        known = self.known_device_ids()
        try:
            idx = known.index(camera_id)
        except ValueError:
            # Unknown id — fall back to hash-derived port. Rare path;
            # the operator must explicitly request an unknown id.
            idx = abs(hash(camera_id)) % 1000
        return _USTREAMER_BASE_PORT + idx

    def _stream_url(self, port: int) -> str:
        """Build the URL the frontend ``<img>`` follows."""
        return f"http://127.0.0.1:{port}/?action=stream"

    def _spawn_locked(
        self, camera_id: str, port: int
    ) -> "subprocess.Popen[bytes]":
        """Spawn ``ustreamer -d <id> -p <port> ...``. Caller holds lock.

        IP camera URLs (HTTP / HTTPS / RTSP) are short-circuited in
        :meth:`spawn_or_reuse` before reaching this helper, so the
        ``camera_id`` here is always a ``/dev/videoN`` path.
        """
        args = [
            "ustreamer",
            "-d", camera_id,
            "-p", str(port),
            *self._USTREAMER_ARGS,
        ]
        try:
            return subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                # Detach so ustreamer does not block the Python loop
                # if its stderr pipe fills up.
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            self._cooldown_until[camera_id] = (
                datetime.now(timezone.utc)
                + timedelta(seconds=self._cooldown_seconds)
            )
            raise RuntimeError(
                "ustreamer is not installed on this host. Run "
                "'sudo apt install ustreamer' on the LinuxCNC controller."
            ) from exc
        except Exception as exc:  # noqa: BLE001 - spawn failure modes vary
            self._cooldown_until[camera_id] = (
                datetime.now(timezone.utc)
                + timedelta(seconds=self._cooldown_seconds)
            )
            raise RuntimeError(
                f"Failed to spawn ustreamer for {camera_id!r}: {exc}"
            ) from exc

    def _terminate_locked(self, camera_id: str) -> None:
        """Terminate ``camera_id``'s child. Caller holds lock."""
        proc = self._procs.pop(camera_id, None)
        if proc is None:
            return
        if proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except Exception:  # noqa: BLE001 - wait timeout path
                    proc.kill()
                    try:
                        proc.wait(timeout=1.0)
                    except Exception:  # noqa: BLE001
                        pass
            except Exception as exc:  # noqa: BLE001 - best-effort cleanup
                logger.debug(
                    "UstreamerSupervisor: terminate raised %s", exc
                )
        self._cooldown_until.pop(camera_id, None)
        logger.info(
            "UstreamerSupervisor: terminated ustreamer id=%s", camera_id
        )


__all__ = ["UstreamerSupervisor"]
