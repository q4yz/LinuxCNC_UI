"""HTTP router for the tools module.

The router is mounted by the registry under
``/api/v1/modules/tools``. It exposes four endpoints — two that
drive the machine via MDI commands, two that surface the
operator-facing tool list:

* ``GET  /tools`` — list every tool the active ``hardware.json``
  declares, overlaid with runtime state (actual / target temp for
  heating tools, actual RPM for digital spindles). The frontend
  ToolPanel polls this every second.
* ``POST /tools/{id}/target`` — set the target temperature for a
  heating tool (extruder / heated_bed). The router looks up the
  tool's ``sensor`` reference and dispatches a ``set_temperature``
  to the hardware layer.
* ``POST /spindle`` — start / reverse / stop a spindle using the
  canonical ``M3 S{speed}`` / ``M4 S{speed}`` / ``M5`` codes.
* ``POST /extruder`` — extrude or retract material on a 3D-printer
  extruder axis using relative (``G91``) ``G1 E{dist} F{speed}``
  moves, restoring absolute (``G90``) mode afterwards.

The two MDI endpoints share the same safety preamble: switch the
task into ``MODE_MDI`` first (blocking until the mode change is
acknowledged) so the subsequent ``mdi`` call is accepted by the
interpreter. The MDI dispatch itself is non-blocking
(``wait_complete(timeout=0)``) because the operator's tool panel
is fire-and-forget — multiple consecutive presses should queue
cleanly rather than stall on a hard wait.

The router intentionally has no ``prefix`` argument — the registry
prefixes it when mounting.
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from hardware import execute_sync_cmd, linuxcnc, linuxcnc_mock
from services.tools_loader import load_active_tools

logger = logging.getLogger("backend.modules.tools.router")


# ---------------------------------------------------------------------- #
# Constants                                                               #
# ---------------------------------------------------------------------- #


# Canonical LinuxCNC MDI strings. Kept module-private so the router
# functions below stay readable. The constants are exported through
# :data:`__all__` for unit tests that want to assert the exact
# strings the endpoint emits (Issue #64 acceptance criteria).
M3_FORWARD = "M3 S{speed}"
M4_BACKWARD = "M4 S{speed}"
M5_STOP = "M5"
G91_RELATIVE = "G91"
G90_ABSOLUTE = "G90"
G1_EXTRUDE = "G1 E{dist} F{speed}"

# Allowed action vocabulary. Centralised so the request validators
# below share a single source of truth.
_SPINDLE_ACTIONS = {"forward", "backward", "stop"}
_EXTRUDER_ACTIONS = {"extrude", "retract"}


# ---------------------------------------------------------------------- #
# Pydantic request models                                                 #
# ---------------------------------------------------------------------- #


class SpindleCommand(BaseModel):
    """Request body for ``POST /spindle``.

    The ``tool_id`` is accepted verbatim and logged so operators can
    correlate a command with the spindle it targeted; the backend
    currently has only one physical spindle so the field is not
    interpreted by the hardware layer.
    """

    tool_id: str = Field(
        ...,
        min_length=1,
        description="Logical tool identifier (e.g., 'spindle_main').",
    )
    action: str = Field(
        ...,
        description="Spindle action: 'forward', 'backward', or 'stop'.",
    )
    speed: int = Field(
        ...,
        ge=0,
        le=200_000,
        description="Target RPM for 'forward' / 'backward'; ignored for 'stop'.",
    )


class ExtruderCommand(BaseModel):
    """Request body for ``POST /extruder``."""

    tool_id: str = Field(
        ...,
        min_length=1,
        description="Logical tool identifier (e.g., 'extruder_1').",
    )
    action: str = Field(
        ...,
        description="Extruder action: 'extrude' or 'retract'.",
    )
    distance: float = Field(
        ...,
        gt=0.0,
        le=1000.0,
        description="Absolute extrusion distance in mm (sign is applied by action).",
    )
    speed: int = Field(
        ...,
        gt=0,
        le=10_000,
        description="Feed rate in mm/min for the G1 move.",
    )


class ToolCommandResponse(BaseModel):
    """Generic response shape for both endpoints."""

    status: str = Field(
        default="success",
        description="Outcome reported by the hardware layer.",
    )
    command: str = Field(
        ...,
        description="The MDI string that was dispatched (or the M5 stop marker).",
    )
    tool_id: str = Field(
        ...,
        description="Echo of the tool id from the request body.",
    )


# ---------------------------------------------------------------------- #
# Tool list / target                                                      #
# ---------------------------------------------------------------------- #


class ToolsResponse(BaseModel):
    """Response body for ``GET /tools``.

    Mirrors the canonical shape the frontend's ``toolStore.ingest``
    accepts: ``{ tools: [...] }`` with each entry carrying the
    hardware.json ``tools[]`` record plus any runtime-state fields
    (``actual`` / ``target`` for heating tools, ``actual_rpm`` for
    digital spindles).
    """

    tools: List[dict] = Field(
        default_factory=list,
        description="Operator-facing tool list, ordered as declared in hardware.json.",
    )


class SetToolTargetRequest(BaseModel):
    """Request body for ``POST /tools/{id}/target``.

    The ``tool_id`` field is accepted but ``{id}`` from the URL is
    canonical (same contract as the temperature module's
    ``POST /sensors/{name}/target``). The target range mirrors
    the temperature module's clamp (0–400 °C) since every heating
    tool ends up dispatching ``set_temperature`` under the hood.
    """

    tool_id: str = Field(
        ...,
        min_length=1,
        description="Logical tool identifier (e.g., 'heater_extruder').",
    )
    target: float = Field(
        ...,
        ge=0.0,
        le=400.0,
        description="Target temperature in Celsius (0–400 °C).",
    )


class SetToolTargetResponse(BaseModel):
    """Response body for ``POST /tools/{id}/target``."""

    status: str = Field(
        default="success",
        description="Outcome reported by the hardware layer.",
    )
    tool_id: str = Field(
        ...,
        description="Echo of the tool id from the URL.",
    )
    target: float = Field(
        ...,
        description="Echo of the target value that was applied.",
    )
    sensor: str = Field(
        ...,
        description="Temperature sensor id the value was dispatched to.",
    )


# ---------------------------------------------------------------------- #
# Endpoints                                                               #
# ---------------------------------------------------------------------- #


# No ``prefix`` — the registry mounts this router under
# ``/api/v1/modules/tools`` and tags it ``modules:tools``.
router = APIRouter(tags=["modules:tools"])


def _ensure_mdi_mode() -> None:
    """Switch the task into MDI mode and wait for the change to commit.

    The interpreter silently ignores ``mdi`` calls issued while the
    task is in ``MANUAL`` / ``AUTO`` mode (see
    :mod:`hardware.linuxcnc_mock`). The machine module's router
    uses the same ``mode`` + ``wait_complete(timeout=5)`` preamble
    before every ``mdi`` dispatch, so we mirror that here.
    """
    execute_sync_cmd(
        "mode",
        5,
        getattr(linuxcnc, "MODE_MDI", 3),
    )


def _dispatch_mdi(command: str) -> None:
    """Issue a single MDI command without waiting for completion.

    The operator's tool panel is fire-and-forget — multiple rapid
    presses should queue rather than block on a hard wait. We pass
    ``timeout=0`` to :func:`hardware.execute_sync_cmd` so the
    underlying ``mdi`` call returns immediately.
    """
    logger.info("tools mdi -> %s", command)
    execute_sync_cmd("mdi", 0, command)


@router.post(
    "/spindle",
    response_model=ToolCommandResponse,
    summary="Control Spindle",
    description=(
        "Start, reverse, or stop the spindle via the canonical "
        "LinuxCNC M-codes: ``M3 S{speed}`` (forward), "
        "``M4 S{speed}`` (backward), or ``M5`` (stop). The router "
        "switches the task into MDI mode before dispatching so the "
        "interpreter accepts the command."
    ),
    operation_id="controlSpindle",
)
def control_spindle(cmd: SpindleCommand) -> ToolCommandResponse:
    """Handle a spindle command request."""
    if cmd.action not in _SPINDLE_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid spindle action: {cmd.action!r}",
        )

    _ensure_mdi_mode()

    if cmd.action == "forward":
        mdi = M3_FORWARD.format(speed=cmd.speed)
    elif cmd.action == "backward":
        mdi = M4_BACKWARD.format(speed=cmd.speed)
    else:  # cmd.action == "stop"
        # M5 ignores the S-word; the request body's ``speed`` is
        # accepted but unused so the front-end doesn't have to
        # branch on action before posting.
        mdi = M5_STOP

    _dispatch_mdi(mdi)
    return ToolCommandResponse(status="success", command=mdi, tool_id=cmd.tool_id)


@router.post(
    "/extruder",
    response_model=ToolCommandResponse,
    description=(
        "Extrude or retract material on the extruder axis. The "
        "router switches into relative distance mode (``G91``), "
        "issues a single ``G1 E{dist} F{speed}`` move — the sign "
        "of ``dist`` is inverted for the retract direction — and "
        "restores absolute mode (``G90``) so subsequent commands "
        "behave as expected."
    ),
    summary="Control Extruder",
    operation_id="controlExtruder",
)
def control_extruder(cmd: ExtruderCommand) -> ToolCommandResponse:
    """Handle an extruder command request."""
    if cmd.action not in _EXTRUDER_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid extruder action: {cmd.action!r}",
        )

    _ensure_mdi_mode()

    # Per Issue #64: retract is a negative distance relative to the
    # extruder's positive-feed direction. The frontend passes an
    # always-positive ``distance`` so the operator never has to
    # remember the sign convention.
    signed_dist = cmd.distance if cmd.action == "extrude" else -cmd.distance

    _dispatch_mdi(G91_RELATIVE)
    move = G1_EXTRUDE.format(dist=signed_dist, speed=cmd.speed)
    _dispatch_mdi(move)
    _dispatch_mdi(G90_ABSOLUTE)

    return ToolCommandResponse(status="success", command=move, tool_id=cmd.tool_id)


# ---------------------------------------------------------------------- #
# Tool list endpoint                                                       #
# ---------------------------------------------------------------------- #


# Tools that surface runtime heat state (``actual`` / ``target``)
# read from ``_machine_state.temperatures``. Spindle / laser
# tools are absent from that dict.
_HEATING_TOOL_TYPES = frozenset({"extruder", "heated_bed"})


def _collect_tools() -> List[dict]:
    """Return the active ``hardware.json`` tool list with runtime state.

    Public helper used by both ``GET /tools`` and the base-thread
    snapshot (``routers/base_thread.py``) so the two surfaces stay
    byte-for-byte identical. Returns an empty list when
    ``hardware.json`` is missing — mirrors the temperature module's
    empty-state behaviour so the ToolPanel renders the "No tools
    configured yet" placeholder instead of failing to mount.
    """
    raw = load_active_tools()
    return [_overlay_runtime_state(tool) for tool in raw]


def _overlay_runtime_state(tool: dict) -> dict:
    """Augment a hardware.json tool record with runtime telemetry.

    Reads from the mock's ``_machine_state`` under the lock so the
    read is consistent — a polling caller never sees a half-updated
    dict. Returns a **shallow copy** of the input so the helper
    cannot accidentally mutate the loader's source list.

    * Heating tools (extruder + heated_bed with a non-null
      ``sensor``): overlay ``actual`` / ``target`` from
      ``_machine_state.temperatures[tool.sensor]``. Defaults to
      ``0.0`` / ``0.0`` when the sensor hasn't been seeded yet
      (e.g. test boot without a hardware.json that names it).
    * ``spindle_digital``: overlay ``actual_rpm`` from
      ``_machine_state.spindle_actual[tool.id]``. Defaults to
      ``0`` when no telemetry has arrived yet.
    * All other tools (spindle_analog, laser): pass through
      unchanged.
    """
    out = dict(tool)
    if tool.get("type") in _HEATING_TOOL_TYPES:
        sensor_id = tool.get("sensor")
        if isinstance(sensor_id, str) and sensor_id:
            with linuxcnc_mock._machine_state.lock:  # noqa: SLF001
                reading = linuxcnc_mock._machine_state.temperatures.get(
                    sensor_id,
                )
            if reading:
                out["actual"] = reading.get("actual", 0.0)
                out["target"] = reading.get("target", 0.0)
            else:
                out["actual"] = 0.0
                out["target"] = 0.0
    elif tool.get("type") == "spindle_digital":
        tool_id = tool.get("id")
        if isinstance(tool_id, str) and tool_id:
            with linuxcnc_mock._machine_state.lock:  # noqa: SLF001
                reading = linuxcnc_mock._machine_state.spindle_actual.get(
                    tool_id,
                )
            out["actual_rpm"] = reading.get("actual", 0) if reading else 0
    return out


@router.get(
    "/tools",
    response_model=ToolsResponse,
    summary="List Operator-Facing Tools",
    description=(
        "Return the ``tools[]`` array from the active "
        "``hardware.json``, augmented with the current runtime "
        "state for each entry: ``actual`` / ``target`` temperature "
        "for heating tools (extruder, heated_bed), ``actual_rpm`` "
        "for digital spindles. The ToolPanel polls this endpoint "
        "every second."
    ),
    operation_id="listTools",
)
def list_tools() -> ToolsResponse:
    """List every tool the active ``hardware.json`` declares.

    Returns an empty list when the file is missing — mirrors the
    temperature module's empty-state behaviour so the ToolPanel
    renders the "No tools configured yet" placeholder instead of
    failing to mount.
    """
    return ToolsResponse(tools=_collect_tools())


# ---------------------------------------------------------------------- #
# Tool target endpoint                                                     #
# ---------------------------------------------------------------------- #


@router.post(
    "/tools/{tool_id}/target",
    response_model=SetToolTargetResponse,
    summary="Set Tool Target Temperature",
    description=(
        "Set the target temperature for a heating tool "
        "(extruder / heated_bed). The router looks up the tool's "
        "``sensor`` reference and dispatches ``set_temperature`` "
        "to the hardware layer — the sensor channel itself is "
        "owned by the temperature module."
    ),
    operation_id="setToolTarget",
)
def set_tool_target(
    tool_id: str, req: SetToolTargetRequest
) -> SetToolTargetResponse:
    """Set the target temperature for ``tool_id``.

    The URL's ``{tool_id}`` is canonical — a body ``tool_id``
    mismatch is logged at DEBUG and ignored. Returns ``404`` when
    the tool is not declared in the active ``hardware.json`` so a
    frontend typo surfaces as a structured error instead of a
    silent no-op. Returns ``400`` when the tool exists but is not
    a heating tool (no ``sensor`` reference).
    """
    if not tool_id or not isinstance(tool_id, str):
        raise HTTPException(
            status_code=400,
            detail="Tool id must be a non-empty string",
        )
    if tool_id != req.tool_id:
        logger.debug(
            "tool_id in body (%r) differs from URL (%r); URL wins",
            req.tool_id,
            tool_id,
        )

    raw_tools = load_active_tools()
    tool = next((t for t in raw_tools if t.get("id") == tool_id), None)
    if tool is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown tool id: {tool_id!r}",
        )
    sensor_id = tool.get("sensor")
    if not isinstance(sensor_id, str) or not sensor_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Tool {tool_id!r} has no temperature sensor "
                "(spindle / laser tools cannot accept a target)"
            ),
        )

    try:
        execute_sync_cmd("set_temperature", 0, sensor_id, req.target)
    except HTTPException:
        # ``execute_sync_cmd`` already produces actionable HTTP
        # errors; surface them verbatim.
        raise
    except Exception as exc:  # noqa: BLE001 - defensive
        logger.error(
            "set_temperature(%s, %s) failed: %s",
            sensor_id,
            req.target,
            exc,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    return SetToolTargetResponse(
        status="success",
        tool_id=tool_id,
        target=req.target,
        sensor=sensor_id,
    )


__all__ = [
    "router",
    "SpindleCommand",
    "ExtruderCommand",
    "ToolCommandResponse",
    "ToolsResponse",
    "SetToolTargetRequest",
    "SetToolTargetResponse",
    "_collect_tools",
    "M3_FORWARD",
    "M4_BACKWARD",
    "M5_STOP",
    "G91_RELATIVE",
    "G90_ABSOLUTE",
    "G1_EXTRUDE",
]