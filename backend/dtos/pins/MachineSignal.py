from dataclasses import dataclass, field
from typing import Optional, TypeVar, Generic, Tuple
from dtos.pins.MachineHalPin import MachineHalPin

T = TypeVar('T')


@dataclass(frozen=True, slots=True)
class MachineHalSignal(Generic[T]):
    """Snapshot of a LinuxCNC HAL signal connecting pins for the visual UI editor."""

    name: str
    source: Optional[MachineHalPin[T]] = None
    targets: Tuple[MachineHalPin[T], ...] = field(default_factory=tuple)
    description: str = ""