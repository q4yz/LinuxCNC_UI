"""Shared helper for reading the active ``hardware.json`` payload.

The temperature module's sensor list (and the mock hardware layer's
temperature simulator) are both seeded from the active
``hardware.json`` so the backend reflects what the operator's
``machine.cfg`` actually declared — not a hard-coded list of three
"sensor" names.

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

import json
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger("backend.services.hardware_loader")


#: Project root = ``<repo>``. Computed relative to this file so the
#: helper resolves correctly regardless of the calling cwd.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ACTIVE_DIR = _PROJECT_ROOT / "machine_config" / "active"
_DEFAULT_HARDWARE_JSON = _DEFAULT_ACTIVE_DIR / "hardware.json"


def _resolve_active_dir(active_dir: Path | None) -> Path:
    """Return the active root, defaulting to ``<repo>/machine_config/active``.

    The helper exposes the ``active_dir`` argument so tests can point at
    a ``tmp_path`` without monkey-patching module-level globals.
    """
    return Path(active_dir) if active_dir is not None else _DEFAULT_ACTIVE_DIR


def load_active_heaters(
    active_dir: Path | None = None,
    hardware_filename: str = "hardware.json",
) -> List[str]:
    """Return the list of sensor ids declared by the active payload.

    Reads ``<active_dir>/<hardware_filename>``, parses the JSON, and
    returns every entry's ``id`` field from the top-level
    ``temperature_sensors`` array. The function name is historical —
    before the v2 hardware.json model, sensors and heaters were the
    same record. The v2 shape splits them; the caller wants the
    sensor list (one entry per runtime temperature channel), not
    the heater list (one entry per controllable thermal output).

    Returns an empty list when:

    * The file does not exist (typical in CI / dev before the first
      ``deploy`` has run).
    * The JSON is malformed (logged at WARNING).
    * The ``temperature_sensors`` key is missing or not an array.
    * The array exists but every entry lacks an ``id`` field.

    Order is preserved as written in ``hardware.json`` — callers that
    want a deterministic order should sort the result themselves.
    """
    active_root = _resolve_active_dir(active_dir)
    path = active_root / hardware_filename
    if not path.exists():
        logger.debug("hardware_loader: %s missing — returning []", path)
        return []

    try:
        with path.open(encoding="utf-8") as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "hardware_loader: failed to parse %s: %s — returning []",
            path,
            exc,
        )
        return []

    if not isinstance(payload, dict):
        return []

    raw_sensors = payload.get("temperature_sensors")
    if not isinstance(raw_sensors, list):
        return []

    names: List[str] = []
    for entry in raw_sensors:
        if isinstance(entry, dict):
            name = entry.get("id")
            if isinstance(name, str) and name:
                names.append(name)
    return names


__all__ = ["load_active_heaters"]