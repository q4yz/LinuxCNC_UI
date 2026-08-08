"""Tests for the heater extractor and the canonical naming helper."""

from __future__ import annotations

import pytest

from modules.machineconfig.compilers.heater_extractor import (
    HardwareHeater,
    HeaterExtractor,
    derive_heater_name,
)
from modules.machineconfig.models import (
    Extruder,
    Heater,
    MachineConfigGraph,
)
from modules.machineconfig.parser import MachineConfigParser


# ---------------------------------------------------------------------- #
# derive_heater_name                                                     #
# ---------------------------------------------------------------------- #


class TestDeriveHeaterName:
    """The naming helper is the single source of truth for section -> name."""

    @pytest.mark.parametrize(
        ("section_name", "expected"),
        [
            ("extruder", "extruder"),
            ("extruder 1", "extruder_1"),
            ("extruder1", "extruder_1"),
            ("extruder 2", "extruder_2"),
            ("extruder2", "extruder_2"),
            ("extruder hotend", "extruder_hotend"),
            ("extruder support", "extruder_support"),
            ("heater_bed", "heater_bed"),
            ("heater_generic", "heater_generic"),
            ("heater_generic chamber", "heater_generic_chamber"),
            ("heater_generic chamber_2", "heater_generic_chamber_2"),
        ],
    )
    def test_named_section(self, section_name: str, expected: str) -> None:
        assert derive_heater_name(section_name) == expected

    def test_extruder_numbered_and_spaced_are_equal(self) -> None:
        """The numbered and spaced forms are intentionally equivalent."""
        assert derive_heater_name("extruder1") == derive_heater_name("extruder 1")
        assert derive_heater_name("extruder2") == derive_heater_name("extruder 2")

    def test_only_extruder_gets_the_numbered_form(self) -> None:
        """heater_* sections do not have a numbered form in Klipper."""
        # heater_bed1 should NOT be normalised to "heater bed 1"
        # because Klipper only defines the numbered form for extruder.
        # The resulting name is "heater_bed1" — the underscore is
        # NOT inserted because the input has no space.
        assert derive_heater_name("heater_bed1") == "heater_bed1"


# ---------------------------------------------------------------------- #
# HardwareHeater strict validation                                       #
# ---------------------------------------------------------------------- #


class TestHardwareHeater:
    """The output model is closed — extra fields raise at construction."""

    def test_minimal_heater(self) -> None:
        h = HardwareHeater(name="extruder")
        assert h.name == "extruder"
        assert h.heater_pin is None
        assert h.sensor_pin is None

    def test_full_heater(self) -> None:
        h = HardwareHeater(
            name="extruder",
            heater_pin="PD5",
            sensor_pin="PA7",
            sensor_type="EPCOS 100K B57560G104F",
            control="pid",
            min_temp=0.0,
            max_temp=250.0,
            pid_Kp=21.527,
            pid_Ki=1.063,
            pid_Kd=108.982,
        )
        assert h.heater_pin == "PD5"
        assert h.pid_Kp == 21.527

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValueError):
            HardwareHeater(name="extruder", unknown_field="oops")


# ---------------------------------------------------------------------- #
# HeaterExtractor                                                        #
# ---------------------------------------------------------------------- #


class TestHeaterExtractor:
    """The extractor is a pure function over MachineConfigGraph."""

    def test_empty_graph(self) -> None:
        graph = MachineConfigGraph()
        assert HeaterExtractor.extract(graph) == []

    def test_extract_from_parsed_example(self) -> None:
        """The user's example (extruder + heater_bed) parses into two heaters."""
        config = """
[extruder]
heater_pin: PD5
sensor_type: EPCOS 100K B57560G104F
sensor_pin: PA7
control: pid
pid_Kp: 21.527
pid_Ki: 1.063
pid_Kd: 108.982
min_temp: 0
max_temp: 250

[heater_bed]
heater_pin: PD4
sensor_type: EPCOS 100K B57560G104F
sensor_pin: PA6
control: pid
pid_Kp: 54.027
pid_Ki: 0.770
pid_Kd: 948.182
min_temp: 0
max_temp: 130
"""
        graph = MachineConfigParser().parse_string(config)
        entries = HeaterExtractor.extract(graph)
        assert [e.name for e in entries] == ["extruder", "heater_bed"]
        heater_bed = entries[1]
        assert heater_bed.heater_pin == "PD4"
        assert heater_bed.max_temp == 130.0
        assert heater_bed.pid_Kp == 54.027

    def test_output_is_sorted_by_name(self) -> None:
        """Sorted output keeps hardware.json diffs stable across runs."""
        config = """
[heater_bed]
heater_pin: PD4
sensor_pin: PA6
control: pid
pid_Kp: 1
pid_Ki: 1
pid_Kd: 1

[extruder]
heater_pin: PD5
sensor_pin: PA7
control: pid
pid_Kp: 1
pid_Ki: 1
pid_Kd: 1

[extruder1]
heater_pin: PD6
sensor_pin: PA8
control: pid
pid_Kp: 1
pid_Ki: 1
pid_Kd: 1
"""
        graph = MachineConfigParser().parse_string(config)
        names = [e.name for e in HeaterExtractor.extract(graph)]
        assert names == ["extruder", "extruder_1", "heater_bed"]

    def test_extruder_stepper_fields_are_dropped(self) -> None:
        """HardwareHeater is the heater slice — no stepper/filament fields."""
        config = """
[extruder]
heater_pin: PD5
sensor_pin: PA7
control: pid
pid_Kp: 1
pid_Ki: 1
pid_Kd: 1
step_pin: PB1
nozzle_diameter: 0.4
"""
        graph = MachineConfigParser().parse_string(config)
        entries = HeaterExtractor.extract(graph)
        assert hasattr(entries[0], "heater_pin")
        # Strict Pydantic: the slice is closed, so stepper/filament
        # fields CANNOT appear on the output even if the source had them.
        # The model_dump is the contract surface.
        payload = entries[0].model_dump()
        assert "step_pin" not in payload
        assert "nozzle_diameter" not in payload

    def test_to_dicts_returns_plain_dicts(self) -> None:
        graph = MachineConfigGraph()
        graph.heaters["heater_bed"] = Heater(
            name="heater_bed",
            heater_pin="PD4",
            sensor_pin="PA6",
            control="pid",
            pid_Kp=1.0,
            pid_Ki=1.0,
            pid_Kd=1.0,
        )
        dicts = HeaterExtractor.to_dicts(graph)
        assert dicts == [
            {
                "name": "heater_bed",
                "heater_pin": "PD4",
                "sensor_pin": "PA6",
                "sensor_type": None,
                "control": "pid",
                "min_temp": None,
                "max_temp": None,
                "pid_Kp": 1.0,
                "pid_Ki": 1.0,
                "pid_Kd": 1.0,
            }
        ]

    def test_extruder_object_passed_through_heater_extractor(self) -> None:
        """An Extruder instance is a Heater — the extractor handles both."""
        graph = MachineConfigGraph()
        graph.heaters["extruder"] = Extruder(
            name="extruder",
            heater_pin="PD5",
            sensor_pin="PA7",
            control="pid",
            pid_Kp=1.0,
            pid_Ki=1.0,
            pid_Kd=1.0,
        )
        entries = HeaterExtractor.extract(graph)
        assert entries[0].name == "extruder"
        assert entries[0].heater_pin == "PD5"
