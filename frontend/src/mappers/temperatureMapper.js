// Temperature wire-shape ↔ entity mapper.
//
// The backend produces a discriminated dict on the base-thread
// snapshot: every entry is either a ``HeaterStateResponse`` (5
// fields: tool_id, target, actual, min_temp, max_temp) or a
// ``TemperatureStateResponse`` (2 fields: tool_id, actual). The
// discriminator is the presence of the ``target`` field — the
// backend never sends ``target`` for a standalone sensor.
//
// This mapper is the **only** place that knows about the
// discriminator. Entity consumers never branch on it.

import { HeaterReading, SensorReading } from "../entities/temperature/Reading.js";
import { ReadingSet } from "../entities/temperature/ReadingSet.js";

/**
 * Convert a single wire entry into the appropriate entity.
 *
 * @param {object} wire The raw snapshot entry.
 * @returns {HeaterReading|SensorReading|null}
 */
export function toReading(wire) {
  if (!wire || typeof wire !== "object") return null;
  if (typeof wire.tool_id !== "string" || wire.tool_id.length === 0) return null;

  const hasHeaterFields = wire.target !== undefined && wire.target !== null;

  if (hasHeaterFields) {
    return new HeaterReading({
      id: wire.tool_id,
      actualCelsius: Number(wire.actual) || 0,
      targetCelsius: Number(wire.target) || 0,
      minTemp: Number.isFinite(Number(wire.min_temp)) ? Number(wire.min_temp) : null,
      maxTemp: Number.isFinite(Number(wire.max_temp)) ? Number(wire.max_temp) : null,
    });
  }
  return new SensorReading({
    id: wire.tool_id,
    actualCelsius: Number(wire.actual) || 0,
  });
}

/**
 * Convert the snapshot's ``sensors`` dict into a ``ReadingSet``.
 *
 * @param {Record<string, object>|null|undefined} dict
 * @returns {ReadingSet}
 */
export function toReadingSet(dict) {
  if (!dict || typeof dict !== "object") {
    return new ReadingSet([]);
  }
  const readings = [];
  for (const wire of Object.values(dict)) {
    const r = toReading(wire);
    if (r) readings.push(r);
  }
  return new ReadingSet(readings);
}

/**
 * Build the wire payload for the legacy temperature setter. Kept
 * here so the router can hand it off without knowing the wire
 * shape.
 */
export function toLegacySetTargetRequest(sensorName, target) {
  return { sensor_name: sensorName, target };
}

/**
 * Build the wire payload for the tools heater setter (the live
 * endpoint). New code should prefer this over the legacy one.
 */
export function toHeaterSetTargetRequest(toolId, target) {
  return { tool_id: toolId, target };
}
