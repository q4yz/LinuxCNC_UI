"""The single UI settings document: store (system service) + reader (any process)."""
from __future__ import annotations

import json

import pytest

from core.ui_settings_reader import read_ui_setting
from core.UiSettingsStore import (
    MAX_VALUE_BYTES,
    InvalidSettingKeyError,
    SettingValueTooLargeError,
    UiSettingsStore,
)


@pytest.fixture()
def store(tmp_path):
    return UiSettingsStore(tmp_path / "settings.json")


def test_unset_store_is_empty_and_has_no_file(store):
    assert store.read_all() == {}
    assert store.read_key("camera.ip_camera_url") is None
    assert not store.path.exists()


def test_round_trip_and_flat_json_on_disk(store):
    assert store.write_key("temperature.unit", "kelvin") == "kelvin"
    store.write_key("dro.macro_buttons", [{"slot": "x", "macro": "zero_x"}])

    assert json.loads(store.path.read_text(encoding="utf-8")) == {
        "dro.macro_buttons": [{"slot": "x", "macro": "zero_x"}],
        "temperature.unit": "kelvin",
    }
    # A fresh store (another process / restart) sees the same values.
    assert UiSettingsStore(store.path).read_key("temperature.unit") == "kelvin"


def test_write_leaves_no_temp_files(store):
    store.write_key("machine.estop_disables_power", True)
    assert [p.name for p in store.path.parent.iterdir()] == ["settings.json"]


def test_delete_returns_to_unset(store):
    store.write_key("temperature.unit", "kelvin")
    assert store.delete_key("temperature.unit") is True
    assert store.has_key("temperature.unit") is False
    assert store.delete_key("temperature.unit") is False  # idempotent


@pytest.mark.parametrize(
    "key",
    ["unit", "../etc.passwd", "camera/ip", "Camera.url", "camera.", ".camera", "camera..url", ""],
)
def test_keys_must_be_namespaced_identifiers(store, key):
    with pytest.raises(InvalidSettingKeyError):
        store.write_key(key, 1)


def test_oversized_value_is_rejected(store):
    with pytest.raises(SettingValueTooLargeError):
        store.write_key("camera.preferences", "x" * (MAX_VALUE_BYTES + 1))
    assert store.read_all() == {}


def test_corrupt_file_reads_as_empty(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert UiSettingsStore(path).read_all() == {}
    assert read_ui_setting("temperature.unit", "celsius", path=path) == "celsius"


def test_reader_is_uncached_and_sees_every_write(store):
    """The machine backend reads the camera keys through the reader —
    a value saved in the UI must be visible immediately."""
    assert read_ui_setting("camera.ip_camera_url", "", path=store.path) == ""
    store.write_key("camera.ip_camera_url", "http://cam-1/stream")
    assert read_ui_setting("camera.ip_camera_url", "", path=store.path) == "http://cam-1/stream"
    store.write_key("camera.ip_camera_url", "http://cam-2/stream")
    assert read_ui_setting("camera.ip_camera_url", "", path=store.path) == "http://cam-2/stream"
