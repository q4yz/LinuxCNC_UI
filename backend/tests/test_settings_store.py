"""Tests for the per-module ``SettingsStore``."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import BaseModel

from core.settings_store import SettingsStore


class _SampleSettings(BaseModel):
    threshold: float = 0.5
    enabled: bool = True


def test_falls_back_to_defaults_when_file_missing(tmp_data_root: Path):
    store = SettingsStore(
        module_id="demo",
        data_root=tmp_data_root,
        defaults=_SampleSettings(),
    )
    payload = store.read_all()
    # Defaults are filled in because no ``settings.json`` exists yet.
    assert payload == {"threshold": 0.5, "enabled": True}
    # ``read_all`` must not create the file.
    assert not store.path.exists()


def test_write_all_creates_file_and_caches(tmp_data_root: Path):
    store = SettingsStore(module_id="demo", data_root=tmp_data_root)
    store.write_all({"threshold": 0.9, "enabled": False, "extra": "x"})

    assert store.path.exists()
    on_disk = json.loads(store.path.read_text(encoding="utf-8"))
    # Defaults are merged underneath the user payload.
    assert on_disk == {
        "threshold": 0.9,
        "enabled": False,
        "extra": "x",
    }

    # Cached: a second read should not touch the filesystem again. We
    # delete the file and re-read — if the cache were broken, the read
    # would crash or return empty.
    store.path.unlink()
    again = store.read_all()
    assert again == {
        "threshold": 0.9,
        "enabled": False,
        "extra": "x",
    }


def test_write_key_merges_with_existing_payload(tmp_data_root: Path):
    store = SettingsStore(module_id="demo", data_root=tmp_data_root)
    store.write_all({"threshold": 0.5})
    store.write_key("enabled", False)

    payload = store.read_all()
    assert payload["threshold"] == 0.5
    assert payload["enabled"] is False


def test_atomic_write_leaves_no_partial_file_on_interrupt(
    tmp_data_root: Path, monkeypatch
):
    """Simulate a crash mid-write and verify ``settings.json`` is intact."""
    store = SettingsStore(module_id="demo", data_root=tmp_data_root)
    store.write_all({"threshold": 0.5})
    original_bytes = store.path.read_bytes()

    # Patch ``os.replace`` to raise *after* the temp file is created.
    # That mimics a process crash between the open() and the rename().
    import core.settings_store as ss_module

    real_replace = os.replace
    calls = {"count": 0}

    def boom(src, dst):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated crash")
        return real_replace(src, dst)

    monkeypatch.setattr(ss_module.os, "replace", boom)

    with pytest.raises(RuntimeError, match="simulated crash"):
        store.write_all({"threshold": 0.99})

    # The original settings.json is still intact (no half-written file).
    assert store.path.read_bytes() == original_bytes

    # No leftover temp file.
    leftovers = list(store.path.parent.glob(".settings-*.json.tmp"))
    assert leftovers == []

    # Subsequent writes still work.
    store.write_all({"threshold": 0.7})
    assert json.loads(store.path.read_text())["threshold"] == 0.7


def test_invalidate_forces_re_read(tmp_data_root: Path):
    store = SettingsStore(module_id="demo", data_root=tmp_data_root)
    store.write_all({"threshold": 0.5})

    # Manually rewrite the file to simulate an external writer, then
    # invalidate the cache and confirm the new value is read.
    store.path.write_text(json.dumps({"threshold": 0.1}))
    assert store.read_all()["threshold"] == 0.5  # still cached
    store.invalidate()
    assert store.read_all()["threshold"] == 0.1


def test_module_id_must_be_non_empty(tmp_data_root: Path):
    with pytest.raises(ValueError):
        SettingsStore(module_id="", data_root=tmp_data_root)