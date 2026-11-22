"""Print tuning: pins, the state DTO, the response."""
from __future__ import annotations

from typing import Iterable, Optional

from dtos.pins.HalPin import HalDataType
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from dtos.print_tuning.PrintTuningDto import PrintObjectDTO, PrintProgressDTO, PrintTuningPins, PrintTuningStateDTO
from models.PrintTuningModels import PrintObject, PrintProgress, PrintTuningState


class PrintTuningMapper:
    @staticmethod
    def create_PrintTuningPins(max_objects: int) -> PrintTuningPins:
        return PrintTuningPins(
            z_offset=ReadWriteDynamicHalPin("z-offset", HalDataType.FLOAT, "Live Z offset (mm), added to Z's external offset"),
            flow=ReadWriteDynamicHalPin("flow", HalDataType.FLOAT, "Flow (%): the extruder component scales the extruder's moves"),
            pressure_advance=ReadWriteDynamicHalPin(
                "pressure-advance", HalDataType.FLOAT, "Pressure advance (mm per mm/s) for the extruder component"),
            exclude_objects=tuple(
                ReadWriteDynamicHalPin(f"exclude-object-{k}", HalDataType.BIT, f"Exclude object {k} of the loaded print")
                for k in range(max_objects)
            ),
        )

    @staticmethod
    def to_state_dto(
        z_offset: float,
        flow: float,
        pressure_advance: float,
        objects: Iterable[str],
        excluded: set[int],
        progress: Optional[tuple[Optional[float], Optional[float]]],
    ) -> PrintTuningStateDTO:
        """The service's live values, the loaded file's objects, and the
        slicer's ``(percent, minutes left)`` at the running line."""
        return PrintTuningStateDTO(
            z_offset=z_offset,
            flow=flow,
            pressure_advance=pressure_advance,
            objects=tuple(PrintObjectDTO(k, name, k in excluded) for k, name in enumerate(objects)),
            progress=None if progress is None else PrintProgressDTO(*progress),
        )

    @staticmethod
    def to_response(dto: PrintTuningStateDTO) -> PrintTuningState:
        return PrintTuningState(
            z_offset=dto.z_offset,
            flow=dto.flow,
            pressure_advance=dto.pressure_advance,
            objects=[PrintObject(index=o.index, name=o.name, excluded=o.excluded) for o in dto.objects],
            progress=None if dto.progress is None else PrintProgress(
                percent=dto.progress.percent, remaining_min=dto.progress.remaining_min),
        )


__all__ = ["PrintTuningMapper"]
