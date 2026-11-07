"""A homing routine's lines -> steps (`.agent/component/homing_override.md`).

Shared by the system backend (the ``.cfg`` parser checks the routine)
and the machine backend (which runs it). A routine is G-code, one
command per line, where ``G28`` means *home* — Klipper's
``[homing_override]`` convention, not LinuxCNC's "go to the G28
position":

* ``G28 X`` / ``G28 X Y`` / ``G28 X0`` — home those axes (values are
  ignored), in the order given;
* ``G28`` alone — home every joint by the INI's ``HOME_SEQUENCE``;
* any other line — sent to LinuxCNC as MDI, waiting until it finished.

LinuxCNC itself cannot home from G-code (homing needs MANUAL mode, a
program runs in AUTO), so the routine runs line by line from the
machine backend instead of as one program — O-word loops and branches
spanning several lines are not supported; a single-line
``o<sub> call`` is.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Axis letters LinuxCNC knows.
AXIS_LETTERS = "XYZABCUVW"

_COMMENT = re.compile(r"\([^)]*\)|;.*$")
_WORD = re.compile(r"([A-Za-z])\s*([-+]?[0-9]*\.?[0-9]*)")


class HomingRoutineError(ValueError):
    """A routine line that cannot run, with its 1-based line number."""

    def __init__(self, line_number: int, line: str, reason: str) -> None:
        self.line_number = line_number
        self.line = line
        self.reason = reason
        super().__init__(f"line {line_number} ({line.strip()!r}): {reason}")


@dataclass(frozen=True)
class HomingStep:
    """One step: ``home`` (``axes`` empty = every joint) or ``mdi``."""

    kind: str
    line: str
    axes: tuple[str, ...] = field(default_factory=tuple)


def _is_g28(value: str) -> bool:
    try:
        return float(value) == 28.0
    except ValueError:
        return False


def parse_homing_routine(text: str) -> list[HomingStep]:
    """The routine's steps, in order. Blank and comment-only lines are
    dropped; raises :class:`HomingRoutineError` for a ``G28`` line that
    also carries other commands."""
    steps: list[HomingStep] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        code = _COMMENT.sub("", line).strip()
        if not code:
            continue
        words = [(letter.upper(), value) for letter, value in _WORD.findall(code)]
        if not any(letter == "G" and _is_g28(value) for letter, value in words):
            steps.append(HomingStep(kind="mdi", line=line))
            continue
        axes: list[str] = []
        for letter, value in words:
            if letter == "G" and _is_g28(value):
                continue
            if letter == "N":
                continue
            if letter not in AXIS_LETTERS:
                raise HomingRoutineError(
                    number, raw, "G28 homes axes; put other commands on their own line"
                )
            if letter not in axes:
                axes.append(letter)
        steps.append(HomingStep(kind="home", line=line, axes=tuple(axes)))
    return steps


def homed_axes(steps: list[HomingStep]) -> set[str] | None:
    """The axis letters the routine homes, or ``None`` when a bare
    ``G28`` homes them all."""
    homed: set[str] = set()
    for step in steps:
        if step.kind != "home":
            continue
        if not step.axes:
            return None
        homed.update(step.axes)
    return homed


__all__ = ["AXIS_LETTERS", "HomingRoutineError", "HomingStep", "homed_axes", "parse_homing_routine"]
