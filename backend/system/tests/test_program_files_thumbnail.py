"""Tests for the G-code file-thumbnail endpoint.

Cura / PrusaSlicer / OrcaSlicer embed a preview PNG at the top of the
exported program as a ``; thumbnail begin/end`` base64 comment block.
``GET /api/v1/programs/thumbnail/{filename}`` extracts the largest
block via a head-scan (never loading multi-megabyte programs fully)
and returns it as a ``data:image/png;base64,…`` URL; ``data_url=None``
for files without one, ``404`` for missing files.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import FilesRouter as files_router_module
from services import ProgramFileService

# Minimal valid PNG-ish payload — the extractor validates the base64
# alphabet, not the PNG signature.
PNG_BYTES = b"\x89PNG\r\n\x1a\n fake-png-bytes"


def _b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def _block(width: int, height: int, payload: bytes) -> str:
    b64 = _b64(payload)
    return (
        f"; thumbnail begin {width}x{height} {len(b64)}\n"
        f"{b64}\n"
        "; thumbnail end\n"
    )


@pytest.fixture()
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path]:
    """FilesRouter mounted against a tmp ``nc_files`` directory.

    The router resolves its service through the module-level
    ``get_program_service`` name-import, so patching it there keeps
    the test hermetic (no shared service-cache involvement).
    """
    nc_files = tmp_path / "nc_files"
    nc_files.mkdir(parents=True)
    monkeypatch.setattr(
        files_router_module,
        "get_program_service",
        lambda: ProgramFileService(root=nc_files),
    )
    app = FastAPI()
    app.include_router(files_router_module.router)
    return TestClient(app), nc_files


def _gcode_with(thumbnail_block: str) -> str:
    return thumbnail_block + "\nG21\nG90\nG1 X10 Y10\n"


# --------------------------------------------------------------------- #
# PrusaSlicer / Orca convention                                          #
# --------------------------------------------------------------------- #


def test_thumbnail_extracts_largest_prusaslicer_block(api):
    client, nc_files = api
    payload = _gcode_with(_block(16, 16, PNG_BYTES) + _block(220, 124, PNG_BYTES))
    (nc_files / "part.ngc").write_text(payload, encoding="utf-8", newline="")

    response = client.get("/api/v1/programs/thumbnail/part.ngc")

    assert response.status_code == 200
    body = response.json()
    assert body["width"] == 220
    assert body["height"] == 124
    assert body["data_url"].startswith("data:image/png;base64,")


def test_thumbnail_handles_cura_block_wrappers(api):
    """Cura's THUMBNAIL_BLOCK markers surround the same inner blocks."""
    client, nc_files = api
    payload = (
        ";THUMBNAIL_BLOCK_START\n"
        + _block(32, 32, PNG_BYTES)
        + ";THUMBNAIL_BLOCK_END\n"
        + "G21\nG90\n"
    )
    (nc_files / "cura.ngc").write_text(payload, encoding="utf-8", newline="")

    response = client.get("/api/v1/programs/thumbnail/cura.ngc")

    assert response.status_code == 200
    body = response.json()
    assert body["width"] == 32
    assert body["data_url"].startswith("data:image/png;base64,")


# --------------------------------------------------------------------- #
# Absent / malformed thumbnails                                          #
# --------------------------------------------------------------------- #


def test_thumbnail_returns_null_data_url_when_absent(api):
    client, nc_files = api
    (nc_files / "plain.ngc").write_text("G21\nG90\nG1 X1\n", encoding="utf-8")

    response = client.get("/api/v1/programs/thumbnail/plain.ngc")

    assert response.status_code == 200
    body = response.json()
    assert body["data_url"] is None
    assert body["width"] is None
    assert body["height"] is None


def test_thumbnail_skips_corrupt_base64_block(api):
    client, nc_files = api
    payload = (
        "; thumbnail begin 220x124 10\n"
        "!!!not-base64!!!\n"
        "; thumbnail end\n"
        + _block(32, 32, PNG_BYTES)
    )
    (nc_files / "corrupt.ngc").write_text(payload, encoding="utf-8", newline="")

    response = client.get("/api/v1/programs/thumbnail/corrupt.ngc")

    assert response.status_code == 200
    body = response.json()
    # The corrupt block is skipped; the valid smaller one is returned.
    assert body["width"] == 32
    assert body["data_url"] is not None


# --------------------------------------------------------------------- #
# Head-scan + error mapping                                              #
# --------------------------------------------------------------------- #


def test_thumbnail_head_scan_avoids_loading_large_files(api):
    client, nc_files = api
    payload = _gcode_with(_block(64, 64, PNG_BYTES)) + "G1 X1\n" + ("x" * 2_000_000)
    (nc_files / "big.ngc").write_text(payload, encoding="utf-8", newline="")

    response = client.get("/api/v1/programs/thumbnail/big.ngc")

    assert response.status_code == 200
    assert response.json()["data_url"] is not None

    # And the service seam really only reads the head.
    service = ProgramFileService(root=nc_files)
    assert len(service.read_head("big.ngc", 4096)) == 4096


def test_thumbnail_returns_404_for_missing_file(api):
    client, _ = api
    response = client.get("/api/v1/programs/thumbnail/nope.ngc")
    assert response.status_code == 404


def test_thumbnail_returns_400_for_path_escape(api):
    """``safe_join`` rejects traversal; the route maps it to 400.

    The ``..%2F`` form is normalised away by HTTP clients before it
    ever reaches the router, so the backslash form (which Starlette
    leaves alone but ``safe_join`` rejects as a path separator) is
    the observable variant.
    """
    client, _ = api
    response = client.get("/api/v1/programs/thumbnail/..%5C..%5Csecrets.ngc")
    assert response.status_code == 400


def test_read_head_rejects_path_escape_directly(api):
    """Service-level guard: traversal raises ``ValueError`` (→ 400)."""
    import pytest as _pytest

    _, nc_files = api
    service = ProgramFileService(root=nc_files)
    with _pytest.raises(ValueError):
        service.read_head("../outside.ngc")
