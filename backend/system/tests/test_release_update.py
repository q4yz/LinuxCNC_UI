"""Release updates: the running/latest version (VersionService,
``GET /api/v1/system/version``) and the prebuilt-dist download
(``scripts/fetch_release.py``) — no network, GitHub is stubbed."""
from __future__ import annotations

import hashlib
import importlib.util
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_file_services.paths import PROJECT_ROOT
from routers import SystemRouter
from services.VersionService import VersionService, parse_version, set_version_service

# -- VersionService --------------------------------------------------------- #


@pytest.mark.parametrize("tag, expected", [
    ("v1.2.10", (1, 2, 10)),
    ("1.0", (1, 0)),
    ("v2.0.0-rc1", None),
    ("abc1234", None),
    (None, None),
])
def test_parse_version(tag, expected):
    assert parse_version(tag) == expected


class _StubVersions(VersionService):
    def __init__(self, nearest=None, latest=None):
        super().__init__()
        self.nearest, self.latest, self.fetches = nearest, latest, 0

    def nearest_tag(self):
        return self.nearest

    def _fetch_latest(self):
        self.fetches += 1
        return self.latest


@pytest.mark.parametrize("nearest, latest, available", [
    ("v1.0.0", "v1.1.0", True),
    ("v1.1.0", "v1.1.0", False),
    ("v1.10.0", "v1.9.0", False),   # numeric, not string comparison
    (None, "v1.0.0", True),         # untagged checkout: any release is an update
    ("v1.0.0", None, False),        # no release / GitHub unreachable
])
def test_release_available(nearest, latest, available):
    assert _StubVersions(nearest=nearest).release_available(latest) is available


def test_latest_release_is_cached():
    versions = _StubVersions(latest="v1.0.0")
    assert versions.latest_release() == versions.latest_release() == "v1.0.0"
    assert versions.fetches == 1


def test_version_endpoint_reports_the_latest_release():
    set_version_service(_StubVersions(nearest="v1.0.0", latest="v1.1.0"))
    try:
        app = FastAPI()
        app.include_router(SystemRouter.router)
        body = TestClient(app).get("/api/v1/system/version").json()
    finally:
        set_version_service(None)
    assert body["latest_version"] == "v1.1.0"
    assert body["update_available"] is True


# -- scripts/fetch_release.py ------------------------------------------------- #


@pytest.fixture()
def fetch_release(monkeypatch):
    spec = importlib.util.spec_from_file_location("fetch_release", PROJECT_ROOT / "scripts" / "fetch_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("LINUXCNC_UI_REPO", "owner/repo")
    return module


def _fake_github(module, monkeypatch, tarball: bytes, checksum: str):
    release = {"tag_name": "v1.2.0", "assets": [
        {"name": module.DIST_ASSET, "browser_download_url": "https://dl/dist"},
        {"name": module.CHECKSUM_ASSET, "browser_download_url": "https://dl/sum"},
    ]}
    responses = {
        "https://api.github.com/repos/owner/repo/releases/latest": json.dumps(release).encode(),
        "https://api.github.com/repos/owner/repo/releases/tags/v1.2.0": json.dumps(release).encode(),
        "https://dl/dist": tarball,
        "https://dl/sum": f"{checksum}  {module.DIST_ASSET}\n".encode(),
    }
    monkeypatch.setattr(module, "_get", lambda url: responses[url])


def test_latest_tag(fetch_release, monkeypatch):
    _fake_github(fetch_release, monkeypatch, b"", "")
    assert fetch_release.release(None)["tag_name"] == "v1.2.0"


def test_download_verifies_the_checksum(fetch_release, monkeypatch, tmp_path):
    data = b"tarball bytes"
    _fake_github(fetch_release, monkeypatch, data, hashlib.sha256(data).hexdigest())
    path = fetch_release.download("v1.2.0", tmp_path)
    assert path.read_bytes() == data


def test_download_rejects_a_corrupt_tarball(fetch_release, monkeypatch, tmp_path):
    _fake_github(fetch_release, monkeypatch, b"corrupt", "0" * 64)
    with pytest.raises(SystemExit, match="Checksum mismatch"):
        fetch_release.download("v1.2.0", tmp_path)
    assert not (tmp_path / fetch_release.DIST_ASSET).exists()
