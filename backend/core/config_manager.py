import os
import logging
import configparser

logger = logging.getLogger(__name__)

class MachineConfig:
    def __init__(self, config_path="machine.cfg"):
        self.config_path = config_path
        # Configure the parser to handle inline comments
        self.parser = configparser.ConfigParser(inline_comment_prefixes=('#', ';'))
        
        if not os.path.exists(self.config_path):
            error_msg = f"Configuration file not found: {self.config_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
            
        self.parser.read(self.config_path)

    def get_heaters(self):
        heaters = {}
        for section in self.parser.sections():
            if section == "heater_bed":
                heaters[section] = {
                    "type": "bed",
                    "max_temp": self.parser.getfloat(section, "max_temp", fallback=120.0),
                    "min_temp": self.parser.getfloat(section, "min_temp", fallback=0.0)
                }
                sensor_type = self.parser.get(section, "sensor_type", fallback=None)
                if sensor_type:
                    heaters[section]["sensor_type"] = sensor_type
                    
            elif section.startswith("extruder"):
                heaters[section] = {
                    "type": "extruder",
                    "max_temp": self.parser.getfloat(section, "max_temp", fallback=300.0),
                    "min_temp": self.parser.getfloat(section, "min_temp", fallback=0.0)
                }
                sensor_type = self.parser.get(section, "sensor_type", fallback=None)
                if sensor_type:
                    heaters[section]["sensor_type"] = sensor_type
                    
        return heaters

    def get_printer_limits(self):
        limits = {
            "kinematics": "cartesian",
            "max_velocity": 300.0,
            "max_accel": 3000.0,
            "minimum_cruise_ratio": 0.5,
            "square_corner_velocity": 5.0
        }
        
        if self.parser.has_section("printer"):
            limits["kinematics"] = self.parser.get("printer", "kinematics", fallback=limits["kinematics"])
            limits["max_velocity"] = self.parser.getfloat("printer", "max_velocity", fallback=limits["max_velocity"])
            limits["max_accel"] = self.parser.getfloat("printer", "max_accel", fallback=limits["max_accel"])
            limits["minimum_cruise_ratio"] = self.parser.getfloat("printer", "minimum_cruise_ratio", fallback=limits["minimum_cruise_ratio"])
            limits["square_corner_velocity"] = self.parser.getfloat("printer", "square_corner_velocity", fallback=limits["square_corner_velocity"])
            
        return limits

    def get_steppers(self):
        steppers = {}
        for section in self.parser.sections():
            if section.startswith("stepper_"):
                steppers[section] = {
                    "step_pin": self.parser.get(section, "step_pin", fallback=None),
                    "dir_pin": self.parser.get(section, "dir_pin", fallback=None),
                    "enable_pin": self.parser.get(section, "enable_pin", fallback=None),
                    "microsteps": self.parser.getint(section, "microsteps", fallback=16),
                    "rotation_distance": self.parser.getfloat(section, "rotation_distance", fallback=40.0),
                    "endstop_pin": self.parser.get(section, "endstop_pin", fallback=None),
                    "position_endstop": self.parser.getfloat(section, "position_endstop", fallback=0.0),
                    "position_min": self.parser.getfloat(section, "position_min", fallback=0.0),
                    "position_max": self.parser.getfloat(section, "position_max", fallback=200.0)
                }
        return steppers
