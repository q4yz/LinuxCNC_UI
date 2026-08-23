import logging

logger = logging.getLogger(__name__)

class MockAxis:
    """Mathematical simulation of an axis managed by the motion controller."""

    JOG_STOP = 0
    JOG_CONTINUOUS = 1
    JOG_INCREMENT = 2

    def __init__(self, axis_index: int):
        self.axis_index = axis_index
        self.current_position = 0.0
        self.jog_mode = self.JOG_STOP
        self.jog_velocity = 0.0
        self.target_position = 0.0

    def jog(self, command: int, velocity: float, distance: float = 0.0):

        if command != 0 and velocity == 0.0:
            velocity = 10.0

        self.jog_mode = command
        self.jog_velocity = velocity



        if command == self.JOG_INCREMENT:
            self.target_position = self.current_position + distance
            logger.info(f"Axis {self.axis_index} incremental jog: target={self.target_position}, vel={velocity}")
        elif command == self.JOG_CONTINUOUS:
            logger.info(f"Axis {self.axis_index} continuous jog: vel={velocity}")
        else:
            logger.info(f"Axis {self.axis_index} stopping.")

    def update(self, delta_time: float):
        """Advances the physics for this axis."""
        if self.jog_mode == self.JOG_CONTINUOUS:
            self.current_position += self.jog_velocity * delta_time

        elif self.jog_mode == self.JOG_INCREMENT:
            step = abs(self.jog_velocity) * delta_time
            if self.current_position < self.target_position:
                self.current_position = min(self.current_position + step, self.target_position)
            elif self.current_position > self.target_position:
                self.current_position = max(self.current_position - step, self.target_position)

            if self.current_position == self.target_position:
                self.jog_mode = self.JOG_STOP