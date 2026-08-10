"""Tests for the Remora signal-map helper.

The helper reads ``hardware.json`` once and exposes two lookups:

* :func:`get_sp_index` — resolves a heater or fan id to its
  ``remora.SP.<n>`` index.
* :func:`get_pv_index` — resolves a temperature sensor id to its
  ``remora.PV.<n>`` index.

The ordering contract mirrors the compiler's
``config_txt_generator``: heater PWMs and their temperature sensors
come first (alphabetical by canonical id), then standalone fan PWMs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.remora_signal_map import (
    get_pv_index,
    get_sp_index,
    invalidate_cache,
)


@pytest.fixture()
def active_dir_with_payload(tmp_path: Path) -> Path:
    """Write a v2 hardware.json fixture and return the active dir."""

    def _make(payload: dict) -> Path:
        target = tmp_path / "active"
        target.mkdir()
        (target / "hardware.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        invalidate_cache()
        return target

    return _make


def test_get_sp_index_returns_heater_index(active_dir_with_payload) -> None:
    """Heater SP indices are sorted alphabetically by canonical id."""
    payload = {
        "version": "2.0",
        "machine": "test",
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": "cartesian",
        "hal_type": "remora",
        "axes": [],
        "steppers": [],
        "drivers": [],
        "endstops": [],
        "heaters": [
            {
                "id": "heater_bed",
                "sensor": "bed",
                "heater_pin": "PA1",
                "control": "watermark",
                "max_temp": 130.0,
            },
            {
                "id": "extruder",
                "sensor": "extruder",
                "heater_pin": "PA2",
                "control": "pid",
                "max_temp": 250.0,
            },
        ],
        "temperature_sensors": [
            {"id": "bed", "pin": "PA3"},
            {"id": "extruder", "pin": "PA4"},
        ],
        "fans": [],
    }
    active = active_dir_with_payload(payload)

    # Alphabetical: extruder (SP.0) before heater_bed (SP.1).
    assert get_sp_index("extruder", active_dir=active) == 0
    assert get_sp_index("heater_bed", active_dir=active) == 1


def test_get_pv_index_returns_sensor_index(active_dir_with_payload) -> None:
    """PV indices are sorted alphabetically by canonical heater id (then sensor)."""
    payload = {
        "version": "2.0",
        "machine": "test",
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": "cartesian",
        "hal_type": "remora",
        "axes": [],
        "steppers": [],
        "drivers": [],
        "endstops": [],
        "heaters": [
            {
                "id": "heater_bed",
                "sensor": "bed",
                "heater_pin": "PA1",
                "control": "watermark",
            },
            {
                "id": "extruder",
                "sensor": "extruder",
                "heater_pin": "PA2",
                "control": "pid",
            },
        ],
        "temperature_sensors": [
            {"id": "bed", "pin": "PA3"},
            {"id": "extruder", "pin": "PA4"},
        ],
        "fans": [],
    }
    active = active_dir_with_payload(payload)

    # Alphabetical: extruder (PV.0) before heater_bed (PV.1).
    assert get_pv_index("extruder", active_dir=active) == 0
    assert get_pv_index("bed", active_dir=active) == 1


def test_get_sp_index_includes_standalone_fans(active_dir_with_payload) -> None:
    """Standalone ``[fan]`` sections get their own SP after the heater PWMs."""
    payload = {
        "version": "2.0",
        "machine": "test",
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": "cartesian",
        "hal_type": "remora",
        "axes": [],
        "steppers": [],
        "drivers": [],
        "endstops": [],
        "heaters": [
            {
                "id": "heater_bed",
                "sensor": "bed",
                "heater_pin": "PA1",
                "control": "watermark",
            },
        ],
        "temperature_sensors": [
            {"id": "bed", "pin": "PA3"},
        ],
        "fans": [
            {"id": "fan_part_cooling", "pin": "PA8"},
        ],
    }
    active = active_dir_with_payload(payload)

    assert get_sp_index("heater_bed", active_dir=active) == 0
    assert get_sp_index("fan_part_cooling", active_dir=active) == 1


def test_unknown_entity_returns_none(active_dir_with_payload) -> None:
    """An entity not in the active payload returns ``None``."""
    payload = {
        "version": "2.0",
        "machine": "test",
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": "cartesian",
        "hal_type": "remora",
        "axes": [],
        "steppers": [],
        "drivers": [],
        "endstops": [],
        "heaters": [],
        "temperature_sensors": [],
        "fans": [],
    }
    active = active_dir_with_payload(payload)

    assert get_sp_index("heater_bed", active_dir=active) is None
    assert get_pv_index("bed", active_dir=active) is None


def test_missing_file_returns_none(tmp_path: Path) -> None:
    """When the file does not exist the helpers return ``None``."""
    invalidate_cache()
    empty = tmp_path / "empty"
    empty.mkdir()

    assert get_sp_index("heater_bed", active_dir=empty) is None
    assert get_pv_index("bed", active_dir=empty) is None


def test_malformed_json_returns_none(tmp_path: Path) -> None:
    """A malformed payload returns ``None`` (no exception)."""
    target = tmp_path / "broken"
    target.mkdir()
    (target / "hardware.json").write_text("not valid json {", encoding="utf-8")
    invalidate_cache()

    assert get_sp_index("heater_bed", active_dir=target) is None


def test_invalidate_cache_refreshes_lookup(tmp_path: Path) -> None:
    """A fresh ``hardware.json`` after ``invalidate_cache`` is honoured."""
    target = tmp_path / "active"
    target.mkdir()

    payload_v1 = {
        "version": "2.0",
        "machine": "test",
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": "cartesian",
        "hal_type": "remora",
        "axes": [],
        "steppers": [],
        "drivers": [],
        "endstops": [],
        "heaters": [
            {
                "id": "heater_bed",
                "sensor": "bed",
                "heater_pin": "PA1",
                "control": "watermark",
            }
        ],
        "temperature_sensors": [{"id": "bed", "pin": "PA3"}],
        "fans": [],
    }
    (target / "hardware.json").write_text(
        json.dumps(payload_v1), encoding="utf-8"
    )
    invalidate_cache()

    assert get_sp_index("heater_bed", active_dir=target) == 0

    # New file lands: the heater is renamed ``heater_bed2`` and a new
    # ``heater_chamber`` appears. The cache must re-read.
    payload_v2 = dict(payload_v1)
    payload_v2["heaters"] = [
        {
            "id": "heater_bed2",
            "sensor": "bed",
            "heater_pin": "PA1",
            "control": "watermark",
        },
        {
            "id": "heater_chamber",
            "sensor": "chamber",
            "heater_pin": "PA0",
            "control": "watermark",
        },
    ]
    payload_v2["temperature_sensors"] = [
        {"id": "bed", "pin": "PA3"},
        {"id": "chamber", "pin": "PA2"},
    ]
    (target / "hardware.json").write_text(
        json.dumps(payload_v2), encoding="utf-8"
    )
    invalidate_cache()

    assert get_sp_index("heater_bed", active_dir=target) is None
    assert get_sp_index("heater_bed2", active_dir=target) == 0
    assert get_sp_index("heater_chamber", active_dir=target) == 1
    assert get_pv_index("chamber", active_dir=target) == 1


def test_heaters_sorted_alphabetically(active_dir_with_payload) -> None:
    """Heater SP ordering follows alphabetical canonical id, not source order."""
    payload = {
        "version": "2.0",
        "machine": "test",
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": "cartesian",
        "hal_type": "remora",
        "axes": [],
        "steppers": [],
        "drivers": [],
        "endstops": [],
        # Source order is bed, extruder, chamber.
        "heaters": [
            {
                "id": "heater_bed",
                "sensor": "bed",
                "heater_pin": "PA1",
                "control": "watermark",
            },
            {
                "id": "extruder",
                "sensor": "extruder",
                "heater_pin": "PA2",
                "control": "pid",
            },
            {
                "id": "heater_generic_chamber",
                "sensor": "chamber",
                "heater_pin": "PA0",
                "control": "watermark",
            },
        ],
        "temperature_sensors": [
            {"id": "bed", "pin": "PA3"},
            {"id": "extruder", "pin": "PA4"},
            {"id": "chamber", "pin": "PA2"},
        ],
        "fans": [],
    }
    active = active_dir_with_payload(payload)

    # Alphabetical: extruder, heater_bed, heater_generic_chamber
    assert get_sp_index("extruder", active_dir=active) == 0
    assert get_sp_index("heater_bed", active_dir=active) == 1
    assert get_sp_index("heater_generic_chamber", active_dir=active) == 2
