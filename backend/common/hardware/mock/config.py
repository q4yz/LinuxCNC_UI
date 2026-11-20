"""What the mock simulates, read from the machine's ``hardware.json``.

The mock used to hard-code a three-axis XYZ machine. It now takes its
axes (letters, joints, travel, speed, home position) and its heater
limits from the same payload the services read, so a 4-axis CNC, a
printer with an extruder joint or a machine with no Z all behave like
the configured machine. An empty payload (no machine yet) keeps the
old XYZ default so the dashboard still has something to move.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

#: LinuxCNC's axis letter order: ``stat.position[i]`` is letter ``AXIS_LETTERS[i]``.
AXIS_LETTERS = "xyzabcuvw"

#: Fallback speed (units/s) for an axis whose config names none.
DEFAULT_AXIS_VELOCITY = 100.0


@dataclass(frozen=True, slots=True)
class MockAxisConfig:
    letter: str
    joints: tuple[int, ...]
    min_limit: float = -math.inf
    max_limit: float = math.inf
    max_velocity: float = DEFAULT_AXIS_VELOCITY
    home: float = 0.0

    @property
    def index(self) -> int:
        return AXIS_LETTERS.index(self.letter)


@dataclass(frozen=True, slots=True)
class MockHeaterConfig:
    max_temp: float | None = None


@dataclass(frozen=True, slots=True)
class MockMachineConfig:
    axes: tuple[MockAxisConfig, ...]
    joint_count: int
    max_velocity: float = DEFAULT_AXIS_VELOCITY
    heaters: Mapping[str, MockHeaterConfig] = field(default_factory=dict)

    def axis(self, letter_index: int) -> MockAxisConfig | None:
        return next((a for a in self.axes if a.index == letter_index), None)

    def axis_of_joint(self, joint: int) -> MockAxisConfig | None:
        return next((a for a in self.axes if joint in a.joints), None)

    @property
    def axis_mask(self) -> int:
        """``stat.axis_mask``: bit ``i`` set for every configured letter."""
        return sum(1 << a.index for a in self.axes)

    @classmethod
    def default(cls) -> "MockMachineConfig":
        """A plain XYZ machine with unlimited travel (no hardware.json)."""
        return cls(axes=tuple(MockAxisConfig(letter, (i,)) for i, letter in enumerate("xyz")), joint_count=3)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "MockMachineConfig":
        payload = payload or {}
        records = [a for a in payload.get("axes") or [] if isinstance(a, dict)]
        axes = tuple(a for a in (_axis(r) for r in records) if a is not None)
        if not axes:
            return cls.default()
        joint_numbers = [
            int(j["joint_number"])
            for j in payload.get("joints") or []
            if isinstance(j, dict) and isinstance(j.get("joint_number"), int)
        ]
        joint_numbers += [j for a in axes for j in a.joints]
        heaters = {
            str(t["id"]): MockHeaterConfig(max_temp=_number(t.get("max_temp")))
            for t in payload.get("tools") or []
            if isinstance(t, dict) and t.get("id")
        }
        return cls(
            axes=axes,
            joint_count=max(joint_numbers) + 1 if joint_numbers else len(axes),
            max_velocity=_number(payload.get("max_velocity")) or DEFAULT_AXIS_VELOCITY,
            heaters=heaters,
        )


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _axis(record: Mapping[str, Any]) -> MockAxisConfig | None:
    letter = str(record.get("id") or "").strip().lower()
    if len(letter) != 1 or letter not in AXIS_LETTERS:
        return None
    joints = tuple(int(j) for j in record.get("joint_numbers") or [] if isinstance(j, int))
    low, high = _number(record.get("position_min")), _number(record.get("position_max"))
    home = _number(record.get("position_endstop"))
    return MockAxisConfig(
        letter=letter,
        joints=joints or (AXIS_LETTERS.index(letter),),
        # A printer's [stepper_x] without position_min travels from 0.
        min_limit=low if low is not None else (0.0 if high is not None else -math.inf),
        max_limit=high if high is not None else math.inf,
        max_velocity=_number(record.get("max_velocity")) or DEFAULT_AXIS_VELOCITY,
        home=home if home is not None else 0.0,
    )


__all__ = ["AXIS_LETTERS", "MockAxisConfig", "MockHeaterConfig", "MockMachineConfig"]
