// Tools wire-shape mapper. Translates the snapshot's ``tools[]``
// array into a discriminated ``ToolList`` of ``SpindleState`` /
// ``ExtruderState`` / ``HeaterReading`` entities.
//
// The backend's three response models are:
//
//   * SpindleDigitalStateResponse — ``id``, ``target_rpm``,
//     ``actual_rpm``, ``is_connected``, ``error_count``,
//     ``last_error``, ``spindle_at_speed``, ``min_rpm``, ``max_rpm``,
//     ``state``.
//
//   * HeaterStateResponse — ``tool_id``, ``target``, ``actual``,
//     ``min_temp``, ``max_temp``. (Note: ``id`` is ``tool_id`` here;
//     every other response model uses ``id``.)
//
//   * ExtruderStateResponse — ``id``, ``heater`` (a nested
//     ``HeaterStateResponse``), ``position``.
//
// The wire shape carries no ``type`` discriminator — the backend
// dropped it when the temperature module moved out of the tools
// overlay. The discriminator lives here as shape detection: every
// other entity consumer reads the typed result and never has to
// branch on wire-shape details.

import { SpindleState } from "../entities/tools/SpindleState.js";
import { ExtruderState } from "../entities/tools/ExtruderState.js";
import { ToolList } from "../entities/tools/ToolList.js";
import { HeaterReading } from "../entities/temperature/Reading.js";

/**
 * Dispatch a single wire row to the right entity. Returns
 * ``null`` for rows that don't match any known shape — the caller
 * (typically :func:`toToolList`) skips them so a half-built
 * snapshot cannot blank the dashboard.
 *
 * Shape rules (no ``type`` field is consulted):
 *
 *   1. ``wire.heater`` is an object → :class:`ExtruderStateResponse`
 *      (extruder with a nested heater).
 *   2. ``wire.tool_id`` is a string + ``wire.target`` +
 *      ``wire.actual`` present → :class:`HeaterStateResponse`
 *      (standalone heater row).
 *   3. ``wire.actual_rpm`` or ``wire.min_v`` present →
 *      :class:`SpindleDigitalStateResponse` or analog spindle.
 *
 * @param {object|null|undefined} wire
 * @returns {SpindleState|ExtruderState|HeaterReading|null}
 */
export function toToolState(wire) {
  if (!wire || typeof wire !== "object") return null;

  // 1. ExtruderStateResponse — nested heater object.
  if (wire.heater && typeof wire.heater === "object") {
    return toExtruderState(wire);
  }

  // 2. HeaterStateResponse — tool_id + target/actual pair, no RPM
  //    fields. The id field is ``tool_id`` on heater rows; every
  //    other response uses ``id``.
  const hasToolId =
    typeof wire.tool_id === "string" && wire.tool_id.length > 0;
  if (
    hasToolId &&
    wire.target !== undefined &&
    wire.actual !== undefined &&
    wire.actual_rpm === undefined &&
    wire.min_v === undefined
  ) {
    return toHeaterReading(wire);
  }

  // 3a. SpindleDigitalStateResponse — has ``actual_rpm``.
  if (typeof wire.actual_rpm !== "undefined") {
    return toSpindleState(wire);
  }

  // 3b. SpindleAnalogStateResponse — no RPM field but ``min_v`` /
  //     ``max_v`` carry the analog voltage range. (The backend
  //     currently dead-ends analog spindles in the response
  //     factory, but the mapper accepts them for forward compat.)
  if (
    typeof wire.min_v !== "undefined" ||
    typeof wire.max_v !== "undefined"
  ) {
    return toSpindleState(wire);
  }

  return null;
}

/**
 * @param {Array<object>|null|undefined} arr
 * @returns {ToolList}
 */
export function toToolList(arr) {
  if (!Array.isArray(arr)) return new ToolList([]);
  const tools = [];
  for (const wire of arr) {
    const t = toToolState(wire);
    if (t) tools.push(t);
  }
  return new ToolList(tools);
}

/**
 * Build a :class:`SpindleState` from the spindle wire shape.
 *
 * @param {object} wire
 * @returns {SpindleState}
 */
export function toSpindleState(wire) {
  return new SpindleState({
    id: wire.id,
    direction: typeof wire.state === "string" ? wire.state : "idle",
    actualRpm: Number(wire.actual_rpm) || 0,
    isConnected: Boolean(wire.is_connected),
    errorCount: Number(wire.error_count) || 0,
    lastError: typeof wire.last_error === "string" ? wire.last_error : "",
    atSpeed: Boolean(wire.spindle_at_speed),
    minRpm: Number(wire.min_rpm) || 0,
    maxRpm: Number(wire.max_rpm) || 24000,
  });
}

/**
 * Build an :class:`ExtruderState` from the extruder wire shape.
 * The nested ``wire.heater`` is a :class:`HeaterStateResponse` —
 * it uses ``tool_id`` (not ``id``), so the nested heater mapper
 * reads from ``tool_id``.
 *
 * @param {object} wire
 * @returns {ExtruderState}
 */
export function toExtruderState(wire) {
  let heater = null;
  if (wire.heater && typeof wire.heater === "object") {
    heater = toHeaterReading(wire.heater);
  } else {
    // Legacy single-heater extruder rows: the outer row carries
    // target / actual / min / max directly.
    heater = new HeaterReading({
      id: wire.id,
      actualCelsius: Number(wire.actual ?? wire.actual_temperature) || 0,
      targetCelsius: Number(wire.target ?? wire.target_temperature) || 0,
      minTemp: Number.isFinite(Number(wire.min_temp))
        ? Number(wire.min_temp)
        : null,
      maxTemp: Number.isFinite(Number(wire.max_temp))
        ? Number(wire.max_temp)
        : null,
    });
  }
  return new ExtruderState({
    id: wire.id,
    position: Number(wire.position) || 0,
    heater,
  });
}

/**
 * Build a :class:`HeaterReading` from the heater wire shape.
 *
 * The backend's :class:`HeaterStateResponse` uses ``tool_id`` for
 * the canonical id field (every other response model uses ``id``).
 * Older snapshots / legacy overlays sometimes still carry ``id``
 * directly — accept both for the migration window, preferring
 * ``tool_id`` when both are present.
 *
 * @param {object} wire
 * @returns {HeaterReading}
 */
export function toHeaterReading(wire) {
  const id =
    typeof wire.tool_id === "string" && wire.tool_id.length > 0
      ? wire.tool_id
      : typeof wire.id === "string" && wire.id.length > 0
        ? wire.id
        : null;
  return new HeaterReading({
    id,
    actualCelsius: Number(wire.actual ?? wire.actual_temperature) || 0,
    targetCelsius: Number(wire.target ?? wire.target_temperature) || 0,
    minTemp: Number.isFinite(Number(wire.min_temp))
      ? Number(wire.min_temp)
      : null,
    maxTemp: Number.isFinite(Number(wire.max_temp))
      ? Number(wire.max_temp)
      : null,
  });
}

/**
 * Wire-shape helpers for write-side commands. The facade hands
 * these to ``ModulesToolsService`` directly — keeping the wire
 * shape in one place means the facade doesn't have to know it.
 */
export function toSpindleCommand({
  toolId,
  action,
  speed,
  masterOverride = 0,
  masterOverrideEnable = false,
  override = 1.0,
}) {
  return {
    tool_id: toolId,
    action,
    speed,
    master_override: masterOverride,
    master_override_enable: masterOverrideEnable,
    override,
  };
}

export function toExtruderCommand({
  toolId,
  action,
  distance,
  speed,
  heaterTarget,
  heaterAction = "set",
}) {
  return {
    tool_id: toolId,
    action,
    distance,
    speed,
    heater: { tool_id: toolId, target: heaterTarget },
    heater_action: heaterAction,
  };
}

export function toHeaterCommand({ toolId, target }) {
  return { tool_id: toolId, target };
}
