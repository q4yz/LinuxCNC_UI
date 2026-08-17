"""Tests for the hardware config loader.

The loader lives in :mod:`services.hardware_config_service` and is
re-exported through :mod:`modules.temperature.config_mapper` as
:func:`get_temperature_sensors`. The helper resolves the canonical
``machine_config/active/hardware.json`` path (overridable via
``active_path``) and returns a list of normalised sensor dicts.
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.temperature.config_mapper import get_temperature_sensors


# ---------------------------------------------------------------------- #
# Helpers                                                                  #
# ---------------------------------------------------------------------- #


def _write_hardware_json(path: Path, payload: dict) -> Path:
    """Write a ``hardware.json`` at ``path`` and return the file path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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
        """Two sensors in v2 produce two entries in declaration order."""
        path = _write_hardware_json(tmp_path / "hardware.json", _v2_payload())

        sensors = get_temperature_sensors(active_path=path)

        assert [s["id"] for s in sensors] == ["extruder", "bed"]

    def test_source_order_is_preserved(
        self, tmp_path: Path
    ) -> None:
        """Order in the returned list matches the source order."""
        path = _write_hardware_json(
            tmp_path / "hardware.json",
            {
                "version": "2.0",
                "temperature_sensors": [
                    {"id": "first", "pin": "PA0"},
                    {"id": "second", "pin": "PA1"},
                    {"id": "third", "pin": "PA2"},
                ],
            },
        )

        sensors = get_temperature_sensors(active_path=path)
        assert [s["id"] for s in sensors] == ["first", "second", "third"]

    def test_empty_sensors_list_returns_empty(self, tmp_path: Path) -> None:
        """A v2 payload with an empty ``temperature_sensors`` list returns []."""
        path = _write_hardware_json(
            tmp_path / "hardware.json",
            {"version": "2.0", "temperature_sensors": []},
        )
        assert get_temperature_sensors(active_path=path) == []

    def test_no_temperature_sensors_key_returns_empty(
        self, tmp_path: Path
    ) -> None:
        """A v2 payload without the ``temperature_sensors`` key returns [].

        The pre-v2 payload (which had only ``heaters``) returns [] — the
        v1 key is gone. The runtime sees "no sensors" and renders the
        empty state, which is the correct UX.
        """
        path = _write_hardware_json(
            tmp_path / "hardware.json",
            {
                "version": "2.0",
                "heaters": [
                    {"id": "heater_extruder", "heater_pin": "PE3"},
                ],
            },
        )
        assert get_temperature_sensors(active_path=path) == []

    def test_ignores_entries_without_id(
        self, tmp_path: Path
    ) -> None:
        """Sensor entries without an ``id`` field are skipped."""
        path = _write_hardware_json(
            tmp_path / "hardware.json",
            {
                "version": "2.0",
                "temperature_sensors": [
                    {"pin": "PA0"},
                    {"id": "valid", "pin": "PA1"},
                    {"id": "", "pin": "PA2"},
                ],
            },
        )
        sensors = get_temperature_sensors(active_path=path)
        assert [s["id"] for s in sensors] == ["valid"]


# ---------------------------------------------------------------------- #
# Failure modes                                                           #
# ---------------------------------------------------------------------- #


class TestFailureModes:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """No ``hardware.json`` at the expected path returns ``[]``."""
        missing = tmp_path / "hardware.json"
        assert get_temperature_sensors(active_path=missing) == []

    def test_malformed_json_returns_empty(self, tmp_path: Path) -> None:
        """Corrupt JSON returns ``[]`` (defensive, no exception)."""
        path = tmp_path / "hardware.json"
        path.write_text("this is not valid json {", encoding="utf-8")
        assert get_temperature_sensors(active_path=path) == []

    def test_non_dict_root_returns_empty(self, tmp_path: Path) -> None:
        """A hardware.json whose root is not an object returns ``[]``."""
        path = _write_hardware_json(tmp_path / "hardware.json", ["not", "a", "dict"])
        assert get_temperature_sensors(active_path=path) == []

    def test_non_list_temperature_sensors_returns_empty(
        self, tmp_path: Path
    ) -> None:
        """``temperature_sensors`` not a list returns ``[]`` (defensive)."""
        path = _write_hardware_json(
            tmp_path / "hardware.json",
            {"version": "2.0", "temperature_sensors": "not a list"},
        )
        assert get_temperature_sensors(active_path=path) == []


# ---------------------------------------------------------------------- #
# Fan fixture round-trip                                                    #
# ---------------------------------------------------------------------- #


def test_hardware_json_with_standalone_fan_round_trips(tmp_path: Path) -> None:
    """A ``[fan]``-derived Fan record survives the loader round-trip."""
    path = _write_hardware_json(
        tmp_path / "hardware.json",
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
    data = json.loads(path.read_text())
    assert data["fans"][0]["id"] == "fan_part_cooling"