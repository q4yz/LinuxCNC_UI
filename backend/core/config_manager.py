import os
import logging
import configparser
from typing import Dict, Optional, List
from pydantic import ValidationError

from .models import (
    HeaterConfig,
    StepperConfig,
    EndstopConfig,
    AxisConfig,
    ExtruderConfig,
    PrinterLimitsConfig,
)

logger = logging.getLogger(__name__)

# --- MachineConfig Manager ---

from pathlib import Path


class MachineConfig:
    """
    Parse and validate machine configuration using Pydantic models.
    Provides type-safe access to heaters, steppers, and printer limits.
    """

    def __init__(self, config_path: str = "machine_config/machine.cfg"):
        # Resolve config path relative to project root so startup cwd doesn't matter
        project_root = Path(__file__).resolve().parents[2]
        cfg_path = Path(config_path)
        if not cfg_path.is_absolute():
            cfg_path = project_root / cfg_path

        self.config_path = str(cfg_path.resolve())
        # Configure the parser to handle inline comments
        self.parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))

        if not Path(self.config_path).exists():
            error_msg = f"Configuration file not found: {self.config_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        self.parser.read(self.config_path)

    def get_heaters(self) -> Dict[str, HeaterConfig | ExtruderConfig]:
        """
        Parse heater configurations and return validated HeaterConfig or ExtruderConfig models.
        
        - For [heater_bed] sections: returns HeaterConfig
        - For [extruder] sections: returns ExtruderConfig (combines HeaterConfig + StepperConfig)
        
        Returns:
            Dict[str, HeaterConfig | ExtruderConfig]: Dictionary of heater/extruder names to validated configs.
            
        Raises:
            ValidationError: If a heater's or extruder's config cannot be validated.
        """
        heaters = {}

        for section in self.parser.sections():
            try:
                if section == "heater_bed":
                    # Parse bed heater configuration
                    heater_data = {
                        "max_temp": self.parser.getfloat(section, "max_temp", fallback=120.0),
                        "min_temp": self.parser.getfloat(section, "min_temp", fallback=0.0),
                    }
                    if self.parser.has_option(section, "control"):
                        heater_data["control"] = self.parser.get(section, "control")
                    if self.parser.has_option(section, "sensor_type"):
                        heater_data["sensor_type"] = self.parser.get(section, "sensor_type")

                    heaters[section] = HeaterConfig(**heater_data)
                    logger.info(f"Loaded heater config: {section}")

                elif section.startswith("extruder"):
                    # Parse extruder configuration: requires both heater and stepper
                    heater_data = {
                        "max_temp": self.parser.getfloat(section, "max_temp", fallback=300.0),
                        "min_temp": self.parser.getfloat(section, "min_temp", fallback=0.0),
                    }
                    if self.parser.has_option(section, "control"):
                        heater_data["control"] = self.parser.get(section, "control")
                    if self.parser.has_option(section, "sensor_type"):
                        heater_data["sensor_type"] = self.parser.get(section, "sensor_type")

                    heater_config = HeaterConfig(**heater_data)

                    # Parse stepper configuration for this extruder
                    stepper_data = {
                        "step_pin": self.parser.get(section, "step_pin", fallback=None),
                        "dir_pin": self.parser.get(section, "dir_pin", fallback=None),
                        "enable_pin": self.parser.get(section, "enable_pin", fallback=None),
                        "microsteps": self.parser.getint(section, "microsteps", fallback=16),
                        "rotation_distance": self.parser.getfloat(section, "rotation_distance", fallback=40.0),
                    }

                    stepper_config = StepperConfig(**stepper_data)

                    # Combine into ExtruderConfig
                    extruder_config = ExtruderConfig(heater=heater_config, stepper=stepper_config)
                    heaters[section] = extruder_config
                    logger.info(f"Loaded extruder config: {section}")

            except ValidationError as e:
                logger.error(f"Validation error in heater/extruder section [{section}]: {e}")
                raise
            except (ValueError, TypeError) as e:
                logger.error(f"Type conversion error in heater/extruder section [{section}]: {e}")
                raise

        return heaters

    def get_printer_limits(self) -> PrinterLimitsConfig:
        """
        Parse printer limits and return a validated PrinterLimitsConfig model.
        
        Returns:
            PrinterLimitsConfig: Validated printer limits configuration.
            
        Raises:
            ValidationError: If the printer config cannot be validated.
        """
        try:
            limits_data = {
                "kinematics": "cartesian",
                "max_velocity": 300.0,
                "max_accel": 3000.0,
                "minimum_cruise_ratio": 0.5,
                "square_corner_velocity": 5.0,
            }

            if self.parser.has_section("printer"):
                if self.parser.has_option("printer", "kinematics"):
                    limits_data["kinematics"] = self.parser.get("printer", "kinematics")
                if self.parser.has_option("printer", "max_velocity"):
                    limits_data["max_velocity"] = self.parser.getfloat("printer", "max_velocity")
                if self.parser.has_option("printer", "max_accel"):
                    limits_data["max_accel"] = self.parser.getfloat("printer", "max_accel")
                if self.parser.has_option("printer", "minimum_cruise_ratio"):
                    limits_data["minimum_cruise_ratio"] = self.parser.getfloat("printer", "minimum_cruise_ratio")
                if self.parser.has_option("printer", "square_corner_velocity"):
                    limits_data["square_corner_velocity"] = self.parser.getfloat("printer", "square_corner_velocity")

            limits = PrinterLimitsConfig(**limits_data)
            logger.info("Loaded printer limits config")
            return limits

        except ValidationError as e:
            logger.error(f"Validation error in printer limits: {e}")
            raise
        except (ValueError, TypeError) as e:
            logger.error(f"Type conversion error in printer limits: {e}")
            raise

    def get_steppers(self) -> Dict[str, AxisConfig]:
        """
        Parse stepper configurations grouped by base axis letter and return validated AxisConfig models.

        Handles Klipper's flat INI structure by grouping multiple steppers (e.g., stepper_y, stepper_y1)
        into a single AxisConfig for the base axis ('y').

        Position limits (position_min, position_max) are extracted only from primary stepper sections
        (e.g., stepper_y, not stepper_y1) to avoid conflicts.

        Returns:
            Dict[str, AxisConfig]: Dictionary mapping base axis letter to validated AxisConfig.
                                   e.g., {"x": AxisConfig(...), "y": AxisConfig(...), "z": AxisConfig(...)}

        Raises:
            ValidationError: If a stepper's or endstop's config cannot be validated.
        """
        axes: Dict[str, AxisConfig] = {}
        axis_steppers: Dict[str, List[StepperConfig]] = {}
        axis_endstops: Dict[str, List[EndstopConfig]] = {}
        axis_limits: Dict[str, tuple] = {}  # (position_min, position_max) per base axis

        for section in self.parser.sections():
            try:
                if section.startswith("stepper_"):
                    # Extract the suffix after "stepper_" (e.g., "stepper_y1" -> "y1")
                    stepper_suffix = section.replace("stepper_", "").lower()

                    # Extract base axis letter (first character: "y1" -> "y", "z" -> "z")
                    base_axis = stepper_suffix[0] if stepper_suffix else None

                    if not base_axis:
                        logger.warning(f"Skipping malformed stepper section: {section}")
                        continue

                    # Initialize axis tracking if not seen before
                    if base_axis not in axis_steppers:
                        axis_steppers[base_axis] = []
                        axis_endstops[base_axis] = []

                    # Parse stepper configuration
                    stepper_data = {
                        "step_pin": self.parser.get(section, "step_pin", fallback=None),
                        "dir_pin": self.parser.get(section, "dir_pin", fallback=None),
                        "enable_pin": self.parser.get(section, "enable_pin", fallback=None),
                        "microsteps": self.parser.getint(section, "microsteps", fallback=16),
                        "rotation_distance": self.parser.getfloat(section, "rotation_distance", fallback=40.0),
                    }

                    stepper_config = StepperConfig(**stepper_data)
                    axis_steppers[base_axis].append(stepper_config)
                    logger.info(f"Loaded stepper config: {section} (base axis: {base_axis})")

                    # Parse endstop if defined in stepper section
                    if self.parser.has_option(section, "endstop_pin"):
                        endstop_data = {
                            "endstop_pin": self.parser.get(section, "endstop_pin"),
                            "position_endstop": self.parser.getfloat(section, "position_endstop", fallback=0.0),
                        }
                        endstop_config = EndstopConfig(**endstop_data)
                        axis_endstops[base_axis].append(endstop_config)
                        logger.info(f"Loaded endstop config for stepper: {section} (base axis: {base_axis})")

                    # CRITICAL: Only extract position_min/position_max from primary stepper
                    # (e.g., "stepper_y", not "stepper_y1") to initialize AxisConfig
                    if stepper_suffix == base_axis and base_axis not in axis_limits:
                        position_min = self.parser.getfloat(section, "position_min", fallback=0.0)
                        position_max = self.parser.getfloat(section, "position_max", fallback=200.0)
                        axis_limits[base_axis] = (position_min, position_max)
                        logger.info(f"Set position limits for axis {base_axis}: [{position_min}, {position_max}]")

            except ValidationError as e:
                logger.error(f"Validation error in stepper section [{section}]: {e}")
                raise
            except (ValueError, TypeError) as e:
                logger.error(f"Type conversion error in stepper section [{section}]: {e}")
                raise

        # Construct AxisConfig for each base axis
        for base_axis, steppers_list in axis_steppers.items():
            try:
                position_min, position_max = axis_limits.get(base_axis, (0.0, 200.0))

                axis_config = AxisConfig(
                    position_min=position_min,
                    position_max=position_max,
                    steppers=steppers_list,
                    endstops=axis_endstops.get(base_axis, []),
                )
                axes[base_axis] = axis_config
                logger.info(f"Created AxisConfig for base axis '{base_axis}' with {len(steppers_list)} stepper(s)")

            except ValidationError as e:
                logger.error(f"Validation error creating AxisConfig for axis [{base_axis}]: {e}")
                raise

        return axes
