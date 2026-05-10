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