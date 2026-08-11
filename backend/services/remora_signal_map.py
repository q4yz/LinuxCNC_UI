"""Map symbolic hardware.json ids to their Remora positional indices.

The compiler emits one Remora firmware module per PWM output
(heater / fan) and one per temperature sensor, in canonical name
order. The hardware.json record carries the unique id
(``heater_bed``, ``extruder``, ``fan_part_cooling``, ``bed``,
``extruder_test``); the Remora firmware only knows the integer
indices (``SP.0``, ``PV.0``). The runtime Python controllers need a
way to resolve a symbolic id to its positional channel without
re-reading the raw ``config.txt``.

This helper reads the canonical ``hardware.json`` once and exposes
two read-only lookup tables:

* :func:`get_sp_index(entity_id)` — maps a heater or fan id to its
  ``remora.SP.<n>`` index (the order the compiler emitted).
* :func:`get_pv_index(entity_id)` — maps a temperature-sensor id to
  its ``remora.PV.<n>`` index.

Cache invalidation mirrors the existing :func:`hardware_loader`:
``invalidate_cache()`` drops the parsed payload so the next lookup
re-reads from disk. The temperature module's ``reseed_from_hardware_json``
hooks already call the sibling ``load_active_heaters``; the new
``invalidate_cache`` here is exposed for callers that swap
``hardware.json`` without going through that path.

Failure modes (missing file, malformed JSON, missing top-level
keys) return ``None`` from the lookup helpers so callers can
distinguish "unknown id" from "offline service". The runtime is
expected to treat ``None`` as "do not control this channel" rather
than crashing — the value is just not addressable today.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("backend.services.remora_signal_map")


# ---------------------------------------------------------------------------
# Path resolution — same convention as hardware_loader.py
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ACTIVE_DIR = _PROJECT_ROOT / "machine_config" / "active"
_DEFAULT_HARDWARE_JSON = _DEFAULT_ACTIVE_DIR / "hardware.json"


def _resolve_active_dir(active_dir: Path | None) -> Path:
    """Return the active root, defaulting to ``<repo>/machine_config/active``."""
    return Path(active_dir) if active_dir is not None else _DEFAULT_ACTIVE_DIR


# ---------------------------------------------------------------------------
# Cached payload
# ---------------------------------------------------------------------------


_cache_lock = threading.Lock()
_cache_payload: Optional[dict] = None
_cache_source: Optional[Path] = None


def _load_payload(
    active_dir: Path | None = None,
    hardware_filename: str = "hardware.json",
) -> Optional[dict]:
    """Read + parse ``hardware.json``; cache the result per path.

    The cache is keyed on the absolute path so two callers using
    different ``active_dir`` arguments get independent snapshots.
    """
    global _cache_payload, _cache_source

    active_root = _resolve_active_dir(active_dir)
    path = active_root / hardware_filename
    try:
        path_resolved = path.resolve()
    except OSError:
        path_resolved = path

    with _cache_lock:
        if _cache_source is not None and _cache_source == path_resolved:
            return _cache_payload

        if not path.exists():
            logger.debug("remora_signal_map: %s missing", path)
            _cache_payload = None
            _cache_source = path_resolved
            return None
        try:
            with path.open(encoding="utf-8") as fp:
                payload = json.load(fp)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "remora_signal_map: failed to parse %s: %s", path, exc
            )
            _cache_payload = None
            _cache_source = path_resolved
            return None
        if not isinstance(payload, dict):
            _cache_payload = None
            _cache_source = path_resolved
            return None
        _cache_payload = payload
        _cache_source = path_resolved
        return payload


# ---------------------------------------------------------------------------
# Index derivation
# ---------------------------------------------------------------------------


def _build_indices(payload: dict) -> tuple[dict[str, int], dict[str, int]]:
    """Build (sp_index_by_id, pv_index_by_id) from a parsed payload.

    The ordering mirrors the compiler's ``config_txt_generator``:
    heater PWMs and their associated temperature sensors come
    first (alphabetical by canonical heater id), then standalone
    fan PWMs (alphabetical). This is the exact contract the HAL's
    ``net pwm_heater_bed_sp => remora.SP.0`` lines rely on, so any
    change here must be matched by the compiler.
    """
    sp: dict[str, int] = {}
    pv: dict[str, int] = {}
    sp_idx = 0
    pv_idx = 0

    heaters = payload.get("heaters") or []
    if isinstance(heaters, list):
        # Canonical name order — match the compiler's sorted iteration.
        sorted_heaters = sorted(
            (h for h in heaters if isinstance(h, dict)),
            key=lambda h: h.get("id", ""),
        )
        sensors_by_id: dict[str, dict] = {}
        for s in payload.get("temperature_sensors") or []:
            if isinstance(s, dict) and isinstance(s.get("id"), str):
                sensors_by_id[s["id"]] = s
        for heater in sorted_heaters:
            heater_id = heater.get("id")
            if not isinstance(heater_id, str) or not heater_id:
                continue
            sp[heater_id] = sp_idx
            sp_idx += 1
            # Match the sensor by the heater's ``sensor`` field if
            # available, else by the canonical strip-prefix form
            # (``heater_bed`` -> ``bed``).
            sensor_id = heater.get("sensor")
            if isinstance(sensor_id, str) and sensor_id in sensors_by_id:
                pv[sensor_id] = pv_idx
                pv_idx += 1
            else:
                canonical_sensor = (
                    heater_id[len("heater_"):]
                    if heater_id.startswith("heater_")
                    else heater_id
                )
                if canonical_sensor in sensors_by_id:
                    pv[canonical_sensor] = pv_idx
                    pv_idx += 1

    fans = payload.get("fans") or []
    if isinstance(fans, list):
        sorted_fans = sorted(
            (f for f in fans if isinstance(f, dict)),
            key=lambda f: f.get("id", ""),
        )
        # Skip fans that originated from heater_pin piggy-backs
        # (they were already counted as heater SPs above); the
        # compiler emits standalone ``[fan]`` sections as their
        # own SP entries. The hardware.json ``id`` convention
        # distinguishes them: ``fan_<heater>`` = piggy-back,
        # ``fan`` / ``fan_<named>`` = standalone.
        seen_piggy = {
            h.get("id") + "_fan"
            for h in sorted_heaters
            if isinstance(h, dict)
        }
        for fan in sorted_fans:
            fan_id = fan.get("id")
            if not isinstance(fan_id, str) or not fan_id:
                continue
            if fan_id in seen_piggy:
                continue
            sp[fan_id] = sp_idx
            sp_idx += 1

    return sp, pv


# ---------------------------------------------------------------------------
# Public lookup API
# ---------------------------------------------------------------------------


def get_sp_index(
    entity_id: str,
    active_dir: Path | None = None,
    hardware_filename: str = "hardware.json",
) -> Optional[int]:
    """Return the Remora ``SP.<n>`` index for ``entity_id``, or ``None``.

    ``entity_id`` is the canonical hardware.json id of a heater or
    fan. Returns ``None`` when the file is missing, malformed, or
    the id is not present in the active payload — the caller
    treats ``None`` as "no channel for this entity today".
    """
    payload = _load_payload(active_dir, hardware_filename)
    if payload is None:
        return None
    sp, _ = _build_indices(payload)
    return sp.get(entity_id)


def get_pv_index(
    entity_id: str,
    active_dir: Path | None = None,
    hardware_filename: str = "hardware.json",
) -> Optional[int]:
    """Return the Remora ``PV.<n>`` index for ``entity_id``, or ``None``.

    ``entity_id`` is the canonical hardware.json id of a temperature
    sensor (``bed``, ``extruder``, ``extruder_test``, ...).
    """
    payload = _load_payload(active_dir, hardware_filename)
    if payload is None:
        return None
    _, pv = _build_indices(payload)
    return pv.get(entity_id)


def invalidate_cache() -> None:
    """Drop the cached payload so the next lookup re-reads from disk.

    Hook for tests and for any caller that swaps ``hardware.json``
    in-process without going through the temperature module's
    ``reseed_from_hardware_json`` path.
    """
    global _cache_payload, _cache_source
    with _cache_lock:
        _cache_payload = None
        _cache_source = None


__all__ = [
    "get_sp_index",
    "get_pv_index",
    "invalidate_cache",
]
