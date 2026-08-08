"""Extract the heaters array from a parsed Klipper graph for ``hardware.json``.

The hardware.json ``heaters`` field is the canonical record of every
temperature-controlled device the backend knows about. It is produced
at compile time from the parsed Klipper configuration and consumed by
the runtime (the temperature module seeds its sensors from this list).

The extraction is a one-way transformation: the input is a
:class:`~.modules.machineconfig.models.MachineConfigGraph`, the
output is a sorted list of :class:`HardwareHeater` Pydantic models
serialised to JSON-safe dicts.

Naming convention lives in :func:`derive_heater_name`. The function
is the single source of truth for the section-header -> heater-name
mapping; the parser uses it for storage and the extractor uses it
for sorting.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..models import MachineConfigGraph


class HardwareHeater(BaseModel):
    """Strict output shape for a ``hardware.json`` heaters entry.

    The model is closed (``extra="forbid"``) so an unexpected field
    on the parser side surfaces as a Pydantic validation error at
    compile time rather than being silently dropped at the consumer.
    Optional fields are typed as ``| None`` so the JSON serialiser
    emits ``null`` for unset values, matching the historical
    ``hardware.json`` shape.
    """

    name: str
    heater_pin: str | None = None
    sensor_pin: str | None = None
    sensor_type: str | None = None
    control: str | None = None
    min_temp: float | None = None
    max_temp: float | None = None
    pid_Kp: float | None = None
    pid_Ki: float | None = None
    pid_Kd: float | None = None

    model_config = ConfigDict(extra="forbid")


def derive_heater_name(section_name: str) -> str:
    """Return the canonical heater name for a Klipper section header.

    Examples:
        ``[extruder]``               -> ``"extruder"``
        ``[extruder 1]``             -> ``"extruder_1"``
        ``[extruder1]``              -> ``"extruder_1"`` (Klipper form)
        ``[extruder hotend]``        -> ``"extruder_hotend"``
        ``[heater_bed]``             -> ``"heater_bed"``
        ``[heater_generic]``         -> ``"heater_generic"``
        ``[heater_generic chamber]`` -> ``"heater_generic_chamber"``

    The numbered ``[extruder<N>]`` form is accepted only for Klipper
    parser compatibility; downstream code sees only the normalised
    ``extruder_<N>`` form produced by this helper. The two forms
    (``[extruder 1]`` and ``[extruder1]``) are intentionally
    equivalent.
    """
    # Normalise [extruder<N>] -> [extruder <N>] so the split below
    # handles both forms identically. Only the extruder section kind
    # has this dual syntax in Klipper; heater_* sections do not.
    if section_name.startswith("extruder") and len(section_name) > len("extruder"):
        rest = section_name[len("extruder"):]
        if rest and rest[0].isdigit():
            section_name = f"extruder {rest}"

    parts = section_name.split(maxsplit=1)
    if len(parts) == 1:
        return section_name
    kind, instance = parts
    return f"{kind}_{instance.replace(' ', '_')}"


class HeaterExtractor:
    """Static extractor: turn a parsed graph into a sorted list of dicts."""

    @staticmethod
    def extract(graph: MachineConfigGraph) -> list[HardwareHeater]:
        """Return every heater on the graph, sorted by canonical name.

        The output list is sorted so ``hardware.json`` diffs remain
        stable across runs. Sorting is by the canonical name
        (e.g. ``extruder``, ``extruder_1``, ``heater_bed``), not by
        source order.

        The function never raises on empty input — an empty graph
        yields an empty list, which the consumer writes as ``[]``.
        """
        return [
            HardwareHeater(
                name=h.name,
                heater_pin=h.heater_pin,
                sensor_pin=h.sensor_pin,
                sensor_type=h.sensor_type,
                control=h.control,
                min_temp=h.min_temp,
                max_temp=h.max_temp,
                pid_Kp=h.pid_Kp,
                pid_Ki=h.pid_Ki,
                pid_Kd=h.pid_Kd,
            )
            for h in sorted(graph.heaters.values(), key=lambda x: x.name)
        ]

    @staticmethod
    def to_dicts(graph: MachineConfigGraph) -> list[dict]:
        """Convenience wrapper that returns plain dicts for JSON dumps.

        Equivalent to ``[h.model_dump() for h in HeaterExtractor.extract(graph)]``
        but without the intermediate Pydantic instances shown to
        callers that just want a JSON-friendly list.
        """
        return [h.model_dump() for h in HeaterExtractor.extract(graph)]


__all__ = [
    "HardwareHeater",
    "HeaterExtractor",
    "derive_heater_name",
]
