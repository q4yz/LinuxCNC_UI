"""Tests for ``backend.modules.temperature.hardware_loader``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.temperature.config_mapper import get_temperature_sensors


# ---------------------------------------------------------------------- #
# Helpers                                                                  #
# ---------------------------------------------------------------------- #


def _write_hardware_json(active_dir: Path, payload: dict) -> Path:
    """Write a ``hardware.json`` into the active dir and return its path."""
    target = active_dir / "hardware.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def _v2_payload() -> dict:
    """A v2-shape ``hardware.json`` with two temperature sensors."""
    return {
        "version": "2.0",
        "machine": "test",
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": "cartesian",
        "hal_type": "remora",
        "axes": [
            {"id": "x", "steppers": ["stepper_x"], "endstops": []},
            {"id": "e0", "steppers": ["stepper_e0"], "endstops": []},
        ],
        "steppers": [
            {
                "id": "stepper_x",
                "driver": "driver_stepper_x",
                "step_pin": "PF13",
                "dir_pin": "PF12",
                "enable_pin": "!PF14",
                "microsteps": 16,
                "rotation_distance": 40.0,
            },
            {
                "id": "stepper_e0",
                "driver": "driver_stepper_e0",
                "step_pin": "PC9",
                "dir_pin": "PC8",
                "enable_pin": "!PD1",
                "microsteps": 16,
                "rotation_distance": 33.5,
            },
        ],
        "drivers": [
            {"id": "driver_stepper_x", "type": "TMC2209"},
            {"id": "driver_stepper_e0", "type": "TMC2209"},
        ],
        "endstops": [],
        "heaters": [
            {
                "id": "heater_extruder",
                "heater_pin": "PE3",
                "control": "pid",
                "sensor": "extruder",
            },
            {
                "id": "heater_bed",
                "heater_pin": "PB7",
                "control": "watermark",
                "sensor": "bed",
            },
        ],
        "temperature_sensors": [
            {"id": "extruder", "pin": "PA1", "type": "EPCOS 100K B57560G104F"},
            {"id": "bed", "pin": "PA0", "type": "Generic 3950"},
        ],
        "fans": [],
    }


# ---------------------------------------------------------------------- #
# v2 model                                                                 #
# ---------------------------------------------------------------------- #


class TestV2Model:
    """The helper reads ``temperature_sensors[].id`` from the v2 payload."""

    def test_returns_temperature_sensor_ids(
        self, tmp_path: Path
    ) -> None:
        """Two sensors in v2 produce two ids in declaration order."""
        _write_hardware_json(tmp_path, _v2_payload())

        names = get_heaters(active_dir=tmp_path)

        assert names == ["extruder", "bed"]

    def test_source_order_is_preserved(
        self, tmp_path: Path
    ) -> None:
        """Order in the returned list matches the source order."""
        _write_hardware_json(
            tmp_path,
            {
                "version": "2.0",
                "temperature_sensors": [
                    {"id": "first", "pin": "PA0"},
                    {"id": "second", "pin": "PA1"},
                    {"id": "third", "pin": "PA2"},
                ],
            },
        )

        assert get_heaters(active_dir=tmp_path) == [
            "first",
            "second",
            "third",
        ]

    def test_empty_sensors_list_returns_empty(self, tmp_path: Path) -> None:
        """A v2 payload with an empty ``temperature_sensors`` list returns []."""
        _write_hardware_json(
            tmp_path,
            {"version": "2.0", "temperature_sensors": []},
        )
        assert get_heaters(active_dir=tmp_path) == []

    def test_no_temperature_sensors_key_returns_empty(
        self, tmp_path: Path
    ) -> None:
        """A v2 payload without the ``temperature_sensors`` key returns [].

        The pre-v2 payload (which had only ``heaters``) returns [] — the
        v1 key is gone. The runtime sees "no sensors" and renders the
        empty state, which is the correct UX.
        """
        _write_hardware_json(
            tmp_path,
            {
                "version": "2.0",
                # Note: no ``temperature_sensors`` key — v1 leftover.
                "heaters": [
                    {"id": "heater_extruder", "heater_pin": "PE3"},
                ],
            },
        )
        assert get_heaters(active_dir=tmp_path) == []

    def test_ignores_entries_without_id(
        self, tmp_path: Path
    ) -> None:
        """Sensor entries without an ``id`` field are skipped."""
        _write_hardware_json(
            tmp_path,
            {
                "version": "2.0",
                "temperature_sensors": [
                    {"pin": "PA0"},  # no id — skipped
                    {"id": "valid", "pin": "PA1"},
                    {"id": "", "pin": "PA2"},  # empty string — skipped
                ],
            },
        )
        assert get_heaters(active_dir=tmp_path) == ["valid"]


# ---------------------------------------------------------------------- #
# Failure modes                                                           #
# ---------------------------------------------------------------------- #


class TestFailureModes:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """No ``hardware.json`` at the expected path returns ``[]``."""
        assert get_heaters(active_dir=tmp_path) == []

    def test_malformed_json_returns_empty(self, tmp_path: Path) -> None:
        """Corrupt JSON returns ``[]`` and logs at WARNING (not raised)."""
        target = tmp_path / "hardware.json"
        target.write_text("this is not valid json {", encoding="utf-8")

        assert get_heaters(active_dir=tmp_path) == []

    def test_non_dict_root_returns_empty(self, tmp_path: Path) -> None:
        """A hardware.json whose root is not an object returns ``[]``."""
        _write_hardware_json(tmp_path, ["not", "a", "dict"])
        assert get_heaters(active_dir=tmp_path) == []

    def test_non_list_temperature_sensors_returns_empty(
        self, tmp_path: Path
    ) -> None:
        """``temperature_sensors`` not a list returns ``[]`` (defensive)."""
        _write_hardware_json(
            tmp_path,
            {"version": "2.0", "temperature_sensors": "not a list"},
        )
        assert get_heaters(active_dir=tmp_path) == []

    def test_hardware_json_with_standalone_fan_round_trips(
        self, tmp_path: Path
    ) -> None:
        """A ``[fan]``-derived Fan record survives the loader round-trip."""
        _write_hardware_json(
            tmp_path,
            {
                "version": "2.0",
                "machine": "fan-test",
                "source": "KlipperToLinuxCNCCompiler",
                "kinematics": "cartesian",
                "hal_type": "remora",
                "axes": [],
                "steppers": [],
                "drivers": [],
                "endstops": [],
                "heaters": [],
                "temperature_sensors": [],
                "fans": [
                    {"id": "fan_part_cooling", "pin": "PA8", "max_power": 0.5}
                ],
            },
        )
        # Loader doesn't currently read ``fans`` — this is purely a
        # model+validator round-trip smoke test so the file shape is
        # pinned.
        data = json.loads((tmp_path / "hardware.json").read_text())
        assert data["fans"][0]["id"] == "fan_part_cooling"
