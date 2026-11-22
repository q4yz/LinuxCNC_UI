import logging
import math

from hardware.mock import constants_mock

logger = logging.getLogger(__name__)


class MockAxis:
    """One axis of the mock trajectory planner: jogs and straight moves,
    held inside the configured travel (soft limits) and speed."""

    JOG_STOP = constants_mock.JOG_STOP
    JOG_CONTINUOUS = constants_mock.JOG_CONTINUOUS
    JOG_INCREMENT = constants_mock.JOG_INCREMENT
    #: Mock-only: a coordinated (MDI / homing) move to ``target_position``.
    MOVE = -1

    #: Jog speed when the caller sends none (units/s).
    DEFAULT_JOG_VELOCITY = 10.0

    def __init__(
        self,
        axis_index: int,
        min_limit: float = -math.inf,
        max_limit: float = math.inf,
        max_velocity: float = math.inf,
        position: float = 0.0,
    ):
        self.axis_index = axis_index
        self.min_limit = min_limit
        self.max_limit = max_limit
        self.max_velocity = max_velocity
        self.current_position = self._clamp(position)
        self.target_position = self.current_position
        self.jog_mode = self.JOG_STOP
        self.jog_velocity = 0.0

    @property
    def moving(self) -> bool:
        return self.jog_mode != self.JOG_STOP

    def _clamp(self, position: float) -> float:
        return min(self.max_limit, max(self.min_limit, position))

    def _speed(self, velocity: float) -> float:
        return min(abs(velocity) or self.DEFAULT_JOG_VELOCITY, self.max_velocity)

    def jog(self, command: int, velocity: float, distance: float = 0.0):
        if command == self.JOG_STOP:
            self.jog_mode = self.JOG_STOP
            logger.debug("Axis %s stopping.", self.axis_index)
            return
        speed = self._speed(velocity)
        self.jog_mode = command
        self.jog_velocity = math.copysign(speed, velocity or 1.0)
        if command == self.JOG_INCREMENT:
            self.target_position = self._clamp(self.current_position + distance)
            self.jog_velocity = speed
        logger.debug("Axis %s jog mode=%s vel=%s target=%s", self.axis_index, command, self.jog_velocity, self.target_position)

    def move_to(self, position: float, velocity: float) -> None:
        """A straight move to ``position`` (clamped to the travel)."""
        self.target_position = self._clamp(position)
        self.jog_velocity = self._speed(velocity)
        self.jog_mode = self.MOVE

    def set_position(self, position: float) -> None:
        """Jump without motion (homing, a test seeding a position)."""
        self.current_position = self._clamp(position)
        self.target_position = self.current_position
        self.jog_mode = self.JOG_STOP

    def update(self, delta_time: float):
        """Advances the physics for this axis."""
        if self.jog_mode == self.JOG_CONTINUOUS:
            position = self.current_position + self.jog_velocity * delta_time
            self.current_position = self._clamp(position)
            if self.current_position != position:  # ran into a soft limit
                self.jog_mode = self.JOG_STOP
        elif self.jog_mode in (self.JOG_INCREMENT, self.MOVE):
            step = abs(self.jog_velocity) * delta_time
            if self.current_position < self.target_position:
                self.current_position = min(self.current_position + step, self.target_position)
            else:
                self.current_position = max(self.current_position - step, self.target_position)
            if self.current_position == self.target_position:
                self.jog_mode = self.JOG_STOP
