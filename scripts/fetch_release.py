#!/usr/bin/env python3
"""Download the prebuilt frontend of a GitHub release.

Boards like the BTT CB1 (1 GB RAM) cannot run ``vite build`` — it
swaps the board to a standstill. CI builds ``frontend/dist`` once per
version tag and attaches it to the GitHub Release
(``.github/workflows/ci.yml``, job ``release``); the release update and
``install.sh --release`` download it with this script instead of
building.

    fetch_release.py tag [<tag>]          print the tag to install (latest release if omitted)
    fetch_release.py download <tag> <dir> download + verify the dist tarball into <dir>,
                                          print the tarball's path

The repository is ``origin``'s GitHub slug, overridable with
``LINUXCNC_UI_REPO=owner/name``.

Standard library only — it runs while the backend services are down.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_ASSET = "linuxcnc-ui-dist.tar.gz"
CHECKSUM_ASSET = DIST_ASSET + ".sha256"
DEFAULT_REPO = "q4yz/LinuxCNC_UI"
TIMEOUT_S = 30


def repo_slug() -> str:
    override = os.environ.get("LINUXCNC_UI_REPO")
    if override:
        return override
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return DEFAULT_REPO
    match = re.search(r"github\.com[:/](.+?/.+?)(?:\.git)?/?$", url)
    return match.group(1) if match else DEFAULT_REPO


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "linuxcnc-ui-updater",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return response.read()


def release(tag: str | None) -> dict:
    """The GitHub release for ``tag`` (latest non-prerelease when ``None``)."""
    base = f"https://api.github.com/repos/{repo_slug()}/releases"
    url = f"{base}/tags/{tag}" if tag else f"{base}/latest"
    return json.loads(_get(url))


def _asset_url(info: dict, name: str) -> str:
    for asset in info.get("assets", []):
        if asset.get("name") == name:
            return asset["browser_download_url"]
    raise SystemExit(f"Release {info.get('tag_name')} has no {name} attached (did the CI release job finish?)")


def download(tag: str, out_dir: Path) -> Path:
    info = release(tag)
    out_dir.mkdir(parents=True, exist_ok=True)
    tarball = out_dir / DIST_ASSET
    data = _get(_asset_url(info, DIST_ASSET))
    expected = _get(_asset_url(info, CHECKSUM_ASSET)).decode().split()[0].lower()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise SystemExit(f"Checksum mismatch for {DIST_ASSET}: expected {expected}, got {actual}")
    tarball.write_bytes(data)
    return tarball


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "tag" and len(argv) <= 3:
        print(release(argv[2] if len(argv) == 3 else None)["tag_name"])
        return 0
    if len(argv) == 4 and argv[1] == "download":
        print(download(argv[2], Path(argv[3])))
        return 0
    print(f"usage: {argv[0]} tag [<tag>] | download <tag> <dir>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except OSError as exc:  # urllib.error.URLError / HTTPError are OSErrors
        print(f"fetch_release: {exc}", file=sys.stderr)
        sys.exit(1)
