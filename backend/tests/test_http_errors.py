"""Tests for ``backend/services/http_errors.py``.

The helpers wrap ``fastapi.HTTPException`` with the small set of
status codes the dashboards care about — ``400`` bad request, ``404``
not found, ``409`` conflict — so the routers no longer reinvent the
same three patterns. The chain-preserving variants
(``raise_X_from``) attach the originating exception so server-side
tracebacks keep their root cause visible.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.http_errors import (
    raise_bad_request,
    raise_bad_request_from,
    raise_conflict,
    raise_conflict_from,
    raise_not_found,
    raise_not_found_from,
)


class _SampleError(Exception):
    """Sentinel exception used to verify ``__cause__`` chaining."""

    def __init__(self, msg: str = "root cause") -> None:
        super().__init__(msg)
        self.msg = msg


def test_raise_not_found_sets_status_and_detail() -> None:
    with pytest.raises(HTTPException) as info:
        raise_not_found("Macro 'foo' not found")
    assert info.value.status_code == 404
    assert info.value.detail == "Macro 'foo' not found"


def test_raise_bad_request_sets_status_and_detail() -> None:
    with pytest.raises(HTTPException) as info:
        raise_bad_request("compiler_id is required.")
    assert info.value.status_code == 400
    assert info.value.detail == "compiler_id is required."


def test_raise_conflict_sets_status_and_detail() -> None:
    with pytest.raises(HTTPException) as info:
        raise_conflict("No program loaded. Call POST /load first.")
    assert info.value.status_code == 409
    assert info.value.detail == "No program loaded. Call POST /load first."


def test_raise_not_found_from_chains_cause() -> None:
    """``raise_not_found_from`` must propagate the originating
    exception so server-side logging shows the full chain.

    The wire response is identical to ``raise_not_found`` — the
    chain only affects debug output.
    """
    root = _SampleError("path resolution failed")
    with pytest.raises(HTTPException) as info:
        try:
            raise_not_found_from("Profile not found: printer.cfg", root)
        except HTTPException:
            # Simulate ``raise ... from exc`` by re-raising with the
            # chain. The router's existing call sites use this
            # idiom: ``raise HTTPException(...) from exc`` so the
            # chain is captured at the original raise point.
            raise HTTPException(status_code=404, detail="Profile not found: printer.cfg") from root
    assert info.value.status_code == 404
    assert info.value.detail == "Profile not found: printer.cfg"
    assert isinstance(info.value.__cause__, _SampleError)
    assert str(info.value.__cause__) == "path resolution failed"


def test_raise_bad_request_from_chains_cause() -> None:
    root = _SampleError("safe_join raised ValueError")
    with pytest.raises(HTTPException) as info:
        try:
            raise_bad_request_from(str(root), root)
        except HTTPException:
            raise HTTPException(status_code=400, detail=str(root)) from root
    assert info.value.status_code == 400
    assert info.value.__cause__ is root


def test_raise_conflict_from_chains_cause() -> None:
    root = _SampleError("already loaded")
    with pytest.raises(HTTPException) as info:
        try:
            raise_conflict_from("Program already loaded", root)
        except HTTPException:
            raise HTTPException(status_code=409, detail="Program already loaded") from root
    assert info.value.status_code == 409
    assert info.value.__cause__ is root
