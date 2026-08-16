"""Shared helper for reading the active ``hardware.json`` payload.

The temperature module's sensor list (and the mock hardware layer's
temperature simulator) are both seeded from the active
``hardware.json`` so the backend reflects what the operator's
``machine.cfg`` actually declared — not a hard-coded list of three
"sensor" names.

This is the canonical home for :func:`load_active_heaters`. The
helper lives next to the temperature module because both consumers
(temperature module + the mock hardware layer) are siblings of
this file — a ``backend.services.hardware_loader`` would create a
top-level import cycle between the temperature module and the
hardware / services layers. The previous :mod:`backend.services.hardware_loader`
was removed; the public surface is now ``from
modules.temperature.hardware_loader import load_active_heaters``.

A single helper keeps the path-resolution and JSON-parse logic in
one place. The mock and the temperature module both call
:func:`load_active_heaters` so a future move to a different active
root only touches this module.

v2 model note
-------------
The v1 hardware.json shape declared a top-level ``heaters`` array of
records where each record carried its own ``name``, ``heater_pin``,
``sensor_pin``, etc. — "the heater carries the sensor". The v2 shape
splits that into a top-level ``heaters`` list (heater records) and
a top-level ``temperature_sensors`` list (sensor records). The two
are linked by the heater's ``sensor`` field which references a
``temperature_sensors[].id``.

The temperature module's sensor list is driven by the sensors, not
the heaters — each sensor in ``temperature_sensors[]`` is one
runtime entry in the mock's ``temperatures`` dict and one row in the
frontend's dynamic form. The function name is historical; the
return value is a list of sensor ids.

Failure modes (missing file, corrupt JSON, missing
``temperature_sensors`` key) return an empty list — the rest of the
system then renders the "No sensors reported yet" empty state
instead of crashing on boot.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from services.hardware_config_service import HardwareConfigService

logger = logging.getLogger("backend.modules.temperature.hardware_loader")

def get_temperature_sensors(active_path: Path | None = None) -> List[str]:
    config_service = HardwareConfigService(active_path)
    raw_sensors = config_service.get_temperature_sensors()

    names: List[str] = []
    for entry in raw_sensors:
        if isinstance(entry, dict):
            name = entry.get("id")
            if isinstance(name, str) and name:
                names.append(name)
    return names


__all__ = ["get_temperature_sensors"]