"""Shared helper for reading the active ``hardware.json`` ``tools[]``.

The tools module's ``GET /tools`` endpoint derives its response
from the active ``hardware.json`` ``tools[]`` list. The temperature
module's sibling helper (:func:`services.hardware_loader.load_active_heaters`)
already consumes the same file but only exposes sensor ids — the
tools module needs the full operator-facing record (id, name, type,
HAL hooks, min/max clamps, …) for every tool the machine declares.

A single helper keeps the path-resolution and JSON-parse logic in
one place. The router calls :func:`load_active_tools` so a future
move to a different active root only touches this module.

Failure modes (missing file, corrupt JSON, missing ``tools`` key,
``tools`` not a list, every entry lacking a usable ``id``) return
an empty list — the router then serves ``{"tools": []}`` and the
ToolPanel renders the "No tools configured yet" empty state
instead of crashing on boot.

The v2 hardware.json model (see
:mod:`backend.modules.machineconfig.models.hardware_json_models`)
already validates every entry's shape and resolves the
``tool.sensor`` / ``tool.fan`` cross-references at compile time,
so this loader intentionally performs no further validation —
it is a pure read.

The :class:`SpindlePins` dataclass and :func:`get_spindle_hal_pin_map`
helper expose the HAL signal aliases every digital spindle declares.
The runtime service addresses spindles by canonical id (``spindle_digital``
for the bare form, ``spindle_digital_test`` for ``[spindle test]``, ...)
and writes the ``signal_*`` HAL pins via ``setp`` (enables) or ``net``
(net signals). A ``None`` pin means "not wired" — the runtime skips it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("backend.modules.tools.tools_loader")


#: Project root = ``<repo>``. Computed relative to this file so the
#: helper resolves correctly regardless of the calling cwd. The
#: depth is ``parents[3]`` because this file now lives under
#: ``backend/modules/tools/`` (originally it was under
#: ``backend/services/`` where ``parents[2]`` was correct). The
#: extra ``../`` walks back through ``modules/`` and ``backend/``
#: to reach the repository root.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _resolve_active_path(active_path: Path | None) -> Path:
    """Return the ``hardware.json`` path, defaulting to the active profile.

    The helper exposes the ``active_path`` argument so tests can
    point at a ``tmp_path`` without monkey-patching module-level
    globals. ``None`` falls back to
    ``<repo>/machine_config/active/hardware.json`` — the path the
    compiler writes after a successful deploy.
    """
    if active_path is not None:
        return Path(active_path)
    return _PROJECT_ROOT / "machine_config" / "active" / "hardware.json"


def load_active_tools(
    active_path: Path | None = None,
) -> List[dict]:
    """Return the operator-facing ``tools[]`` array from ``hardware.json``.

    Reads ``<active_path>/hardware.json``, parses the JSON, and
    returns every entry of the top-level ``tools`` array as a
    plain dict. The caller (the router) overlays the runtime
    state — actual / target temperature for heating tools, actual
    RPM for digital spindles — so this helper returns the raw
    records unchanged.

    Returns an empty list when:

    * The file does not exist (typical in CI / dev before the
      first ``deploy`` has run).
    * The JSON is malformed (logged at WARNING).
    * The ``tools`` key is missing or not a list.
    * The list exists but every entry lacks an ``id`` field.

    Order is preserved as written in ``hardware.json`` — callers
    that want a deterministic order should sort the result
    themselves. The ToolPanel chip row preserves source order so
    the operator sees tools in the order the compiler emitted
    them.
    """
    path = _resolve_active_path(active_path)
    if not path.exists():
        logger.debug("tools_loader: %s missing — returning []", path)
        return []

    try:
        with path.open(encoding="utf-8") as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "tools_loader: failed to parse %s: %s — returning []",
            path,
            exc,
        )
        return []

    if not isinstance(payload, dict):
        return []

    raw_tools = payload.get("tools")
    if not isinstance(raw_tools, list):
        return []

    out: List[dict] = []
    for entry in raw_tools:
        if not isinstance(entry, dict):
            continue
        # ``id`` is the canonical machine handle. An entry without
        # an ``id`` cannot be addressed by the operator or the
        # frontend, so skip it — the strict v2 model would have
        # already rejected it at compile time, but defensive
        # parsing here keeps the loader robust to legacy /
        # hand-written payloads.
        if not isinstance(entry.get("id"), str) or not entry["id"]:
            continue
        out.append(entry)
    return out


__all__ = ["load_active_tools", "SpindlePins", "get_spindle_hal_pin_map"]


# ---------------------------------------------------------------------- #
# Spindle HAL pin map                                                     #
# ---------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SpindlePins:
    """The HAL signal aliases for one digital spindle.

    Field names mirror the ``signal_*`` keys emitted by
    :func:`backend.modules.machineconfig.compilers.hardware_json_generator._tool_payload_from_spindle_digital`
    on each ``tools[]`` entry of type ``spindle_digital`` — keeping
    the runtime vocabulary aligned with what the compiler already
    produces.

    Every field is optional; a ``None`` value means "not wired" and
    the runtime service skips it. The dataclass is frozen so the
    helper can safely share a single record across threads without
    defensive copying.

    Attributes
    ----------
    id:
        Canonical hardware.json id (``spindle_digital`` for the
        bare form, ``spindle_digital_test`` for ``[spindle test]``).
    at_speed:
        pyvcp signal that turns on when the spindle is at-speed.
    forward:
        HAL pin that latches the forward direction (write ``1`` to
        start spinning forward when ``on`` is also ``1``).
    reverse:
        HAL pin that latches the reverse direction (write ``1`` to
        start spinning backward when ``on`` is also ``1``).
    on:
        Master enable — written ``1`` to energise the spindle,
        ``0`` to drop it. Forward/reverse only take effect while
        ``on`` is asserted.
    pwm:
        pyvcp signal mirroring the current PWM / target frequency.
    rpm_out:
        pyvcp signal mirroring the live RPM feedback.
    istop:
        pyvcp signal that turns on when the VFD reported an
        immediate-stop event.
    estop:
        pyvcp signal that turns on when the VFD reported an error
        (last-error string).
    vfd_enable:
        HAL pin that arms the VFD for accepting commands (separate
        from the per-direction enables).
    """

    id: str
    at_speed:  Optional[str] = None
    forward:   Optional[str] = None
    reverse:   Optional[str] = None
    on:        Optional[str] = None
    pwm:       Optional[str] = None
    rpm_out:   Optional[str] = None
    istop:     Optional[str] = None
    estop:     Optional[str] = None
    vfd_enable: Optional[str] = None


def get_spindle_hal_pin_map(
    active_path: Path | None = None,
) -> Dict[str, SpindlePins]:
    """Return ``{spindle_id: SpindlePins}`` for every digital spindle.

    Reads ``<active_path>/hardware.json`` (defaulting to
    ``<repo>/machine_config/active/hardware.json``), filters
    ``tools[]`` for ``type == "spindle_digital"`` and builds one
    :class:`SpindlePins` per entry. The map is keyed by the canonical
    tool id (the same id the compiler emits and the runtime uses for
    control commands), so callers can address a specific spindle by
    id and receive every HAL signal name it knows about.

    Failure modes (file missing, corrupt JSON, ``tools`` not a list,
    no ``spindle_digital`` entries, an entry without a usable id)
    return an empty dict. A missing / unparseable file is logged at
    WARNING so the operator can see why the spindle card never
    rendered.

    Order is preserved as written in ``hardware.json`` — callers
    that want a deterministic order should sort the result
    themselves.
    """
    path = _resolve_active_path(active_path)
    if not path.exists():
        logger.debug("spindle_loader: %s missing — returning {}", path)
        return {}

    try:
        with path.open(encoding="utf-8") as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "spindle_loader: failed to parse %s: %s — returning {}",
            path,
            exc,
        )
        return {}

    if not isinstance(payload, dict):
        return {}

    raw_tools = payload.get("tools")
    if not isinstance(raw_tools, list):
        return {}

    out: Dict[str, SpindlePins] = {}
    for entry in raw_tools:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "spindle_digital":
            continue
        tool_id = entry.get("id")
        if not isinstance(tool_id, str) or not tool_id:
            # No usable handle — the compiler would have rejected
            # this at validation time, but defensive parsing here
            # keeps the loader robust to legacy / hand-written
            # payloads.
            continue
        out[tool_id] = SpindlePins(
            id=tool_id,
            at_speed=_as_optional_str(entry.get("signal_at_speed")),
            forward=_as_optional_str(entry.get("signal_forward")),
            reverse=_as_optional_str(entry.get("signal_reverse")),
            on=_as_optional_str(entry.get("signal_on")),
            pwm=_as_optional_str(entry.get("signal_pwm")),
            rpm_out=_as_optional_str(entry.get("signal_rpm_out")),
            istop=_as_optional_str(entry.get("signal_istop")),
            estop=_as_optional_str(entry.get("signal_estop")),
            vfd_enable=_as_optional_str(entry.get("signal_vfd_enable")),
        )
    return out


def _as_optional_str(value: object) -> Optional[str]:
    """Coerce ``value`` to ``Optional[str]`` for :class:`SpindlePins`.

    Anything that is not a non-empty string becomes ``None`` so the
    dataclass never stores a literal ``""`` placeholder that the
    runtime would treat as a wired pin.
    """
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None