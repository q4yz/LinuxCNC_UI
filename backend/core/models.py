"""
Pydantic models for machine configuration validation.

This module defines type-safe configuration models for:
- Heater devices (bed, extruders)
- Stepper motors and axes
- Printer motion limits and kinematics
- Endstop sensors
"""

from typing import Dict, Optional, List
from pydantic import BaseModel, Field


class HeaterConfig(BaseModel):
    """Configuration for heater devices (extruder, bed, etc.)."""
    max_temp: float = Field(default=300.0, description="Maximum safe temperature in Celsius")
    min_temp: float = Field(default=0.0, description="Minimum safe temperature in Celsius")
    control: Optional[str] = Field(default=None, description="Control algorithm (either pid or watermark)")
    sensor_type: Optional[str] = Field(default=None, description="Sensor type identifier (e.g., 'PT100', 'NTC')")

    class Config:
        """Pydantic config for strict validation."""
        validate_assignment = True


class EndstopConfig(BaseModel):
    """Configuration for endstop sensors."""
    endstop_pin: Optional[str] = Field(default=None, description="GPIO pin for endstop sensor")
    position_endstop: float = Field(default=0.0, description="Position of endstop in mm")

    class Config:
        """Pydantic config for strict validation."""
        validate_assignment = True


class StepperConfig(BaseModel):
    """Configuration for stepper motor axes."""
    step_pin: str = Field(..., description="GPIO pin for step signal")
    dir_pin: str = Field(..., description="GPIO pin for direction signal")
    enable_pin: str = Field(..., description="GPIO pin for enable signal")
    microsteps: int = Field(default=16, description="Microsteps per full step")
    rotation_distance: float = Field(default=40.0, description="Distance per full rotation in mm")

    class Config:
        """Pydantic config for strict validation."""
        validate_assignment = True


class PrinterLimitsConfig(BaseModel):
    """Printer kinematics and motion limits."""
    kinematics: str = Field(default="cartesian", description="Machine kinematics type")
    max_velocity: float = Field(default=300.0, description="Maximum velocity in mm/s")
    max_accel: float = Field(default=3000.0, description="Maximum acceleration in mm/s²")
    minimum_cruise_ratio: float = Field(default=0.5, description="Minimum cruise ratio (0.0-1.0)")
    square_corner_velocity: float = Field(default=5.0, description="Square corner velocity in mm/s")

    class Config:
        """Pydantic config for strict validation."""
        validate_assignment = True


class AxisConfig(BaseModel):
    """Configuration for axes (X, Y, Z, etc.)."""
    position_min: float = Field(default=0.0, description="Minimum position limit in mm")
    position_max: float = Field(default=200.0, description="Maximum position limit in mm")
    endstops: List[EndstopConfig] = Field(default_factory=list, description="List of endstops for this axis")
    steppers: List[StepperConfig] = Field(default_factory=list, description="List of stepper configurations for this axis")

    class Config:
        """Pydantic config for strict validation."""
        validate_assignment = True


class ExtruderConfig(BaseModel):
    """Configuration for extruder components (heater + stepper)."""
    heater: HeaterConfig = Field(..., description="Heater configuration for this extruder")
    stepper: StepperConfig = Field(..., description="Stepper configuration for this extruder")

    class Config:
        """Pydantic config for strict validation."""
        validate_assignment = True
