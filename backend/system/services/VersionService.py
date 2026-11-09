"""Running version and the latest GitHub release, for the update card.

The running version comes from git (``git describe --tags``: the tag on
a release install, ``v1.2.0-3-gabc1234`` on a commit build). The latest
release is asked from the GitHub API — short timeout, cached, and an
offline machine simply reports ``None`` instead of failing the request.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

from domain_file_services.paths import PROJECT_ROOT

logger = logging.getLogger("backend.services.VersionService")

DEFAULT_REPO = "q4yz/LinuxCNC_UI"
#: GitHub allows 60 unauthenticated API calls per hour and IP.
CACHE_TTL_S = 600.0
FAILED_RETRY_S = 60.0
TIMEOUT_S = 3.0
#: The release asset the release update installs (scripts/fetch_release.py).
DIST_ASSET = "linuxcnc-ui-dist.tar.gz"


def parse_version(tag: Optional[str]) -> Optional[tuple[int, ...]]:
    """``v1.2.10`` -> ``(1, 2, 10)``; ``None`` for anything that is no version tag."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (tag or "").strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


class VersionService:
    def __init__(self, project_root: Path = PROJECT_ROOT) -> None:
        self._root = project_root
        self._lock = threading.Lock()
        self._latest: Optional[str] = None
        self._releases: list[dict[str, Any]] = []
        self._releases_at: Optional[float] = None
        self._releases_ttl: float = CACHE_TTL_S
        # None = never checked. Not 0.0: monotonic() counts from boot, so
        # on a freshly booted machine it can still be below the TTL.
        self._checked_at: Optional[float] = None
        self._ttl = CACHE_TTL_S

    # -- running version -------------------------------------------------- #

    def _git(self, *args: str) -> Optional[str]:
        try:
            result = subprocess.run(
                ["git", *args], cwd=str(self._root),
                capture_output=True, text=True, check=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("git %s failed: %s", " ".join(args), exc)
            return None
        return result.stdout.strip() or None

    def commit(self) -> str:
        return self._git("rev-parse", "--short", "HEAD") or "unknown"

    def describe(self) -> str:
        return self._git("describe", "--tags", "--always") or "unknown"

    def nearest_tag(self) -> Optional[str]:
        return self._git("describe", "--tags", "--abbrev=0")

    # -- latest release --------------------------------------------------- #

    def repo_slug(self) -> str:
        override = os.environ.get("LINUXCNC_UI_REPO")
        if override:
            return override
        match = re.search(r"github\.com[:/](.+?/.+?)(?:\.git)?/?$", self._git("remote", "get-url", "origin") or "")
        return match.group(1) if match else DEFAULT_REPO

    def _fetch_latest(self) -> Optional[str]:
        url = f"https://api.github.com/repos/{self.repo_slug()}/releases/latest"
        request = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "linuxcnc-ui",
        })
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                tag = json.loads(response.read()).get("tag_name")
        except (OSError, ValueError) as exc:  # offline, 404 (no release yet), rate limit
            logger.info("Latest release unavailable: %s", exc)
            return None
        return tag if isinstance(tag, str) else None

    def latest_release(self) -> Optional[str]:
        with self._lock:
            if self._checked_at is None or time.monotonic() - self._checked_at > self._ttl:
                self._latest = self._fetch_latest()
                self._checked_at = time.monotonic()
                self._ttl = CACHE_TTL_S if self._latest else FAILED_RETRY_S
            return self._latest

    def _fetch_releases(self) -> Optional[list[dict[str, Any]]]:
        """Every GitHub release, newest first (one page of 100 — plenty)."""
        url = f"https://api.github.com/repos/{self.repo_slug()}/releases?per_page=100"
        request = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "linuxcnc-ui",
        })
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                data = json.loads(response.read())
        except (OSError, ValueError) as exc:
            logger.info("Release list unavailable: %s", exc)
            return None
        if not isinstance(data, list):
            return None
        out = []
        for item in data:
            if not isinstance(item, dict) or item.get("draft") or not isinstance(item.get("tag_name"), str):
                continue
            assets = {a.get("name") for a in item.get("assets") or [] if isinstance(a, dict)}
            out.append({
                "tag": item["tag_name"],
                "name": item.get("name") or item["tag_name"],
                "published_at": item.get("published_at"),
                "prerelease": bool(item.get("prerelease")),
                # The release update needs the CI's prebuilt UI.
                "installable": DIST_ASSET in assets,
            })
        return out

    def releases(self) -> list[dict[str, Any]]:
        """Every release (pre-releases included), cached like :meth:`latest_release`."""
        with self._lock:
            stale = self._releases_at is None or time.monotonic() - self._releases_at > self._releases_ttl
            if stale:
                fetched = self._fetch_releases()
                self._releases_at = time.monotonic()
                self._releases_ttl = CACHE_TTL_S if fetched is not None else FAILED_RETRY_S
                if fetched is not None:
                    self._releases = fetched
            return list(self._releases)

    def release_available(self, latest: Optional[str]) -> bool:
        """``latest`` is newer than the release this checkout is on / based on."""
        latest_v = parse_version(latest)
        if latest_v is None:
            return False
        current_v = parse_version(self.nearest_tag())
        return current_v is None or latest_v > current_v


_SERVICE_INSTANCE: Optional[VersionService] = None


def get_version_service() -> VersionService:
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = VersionService()
    return _SERVICE_INSTANCE


def set_version_service(service: Optional[VersionService]) -> None:
    global _SERVICE_INSTANCE
    _SERVICE_INSTANCE = service


__all__ = ["VersionService", "get_version_service", "parse_version", "set_version_service"]
