import { HeaterReading, SensorReading } from "../entities/temperature/Reading";
import { ReadingSet, type AnyReading } from "../entities/temperature/ReadingSet";

import type {
  HeaterStateResponse,
  TemperatureStateResponse,
} from "../../generated/api";

// The union of valid temperature wire shapes
export type AnyTemperatureWire = HeaterStateResponse | TemperatureStateResponse;

/**
 * Convert a single wire entry into the appropriate entity.
 * Uses the explicit `type` field discriminator.
 */
export function toReading(wire: AnyTemperatureWire | Record<string, any> | null | undefined): AnyReading | null {
  if (!wire || typeof wire !== "object") return null;
  if (typeof wire.tool_id !== "string" || wire.tool_id.length === 0) return null;

  // 1. Primary path: Use the explicit type discriminator
  if ("type" in wire) {
    switch (wire.type) {
      case "heater":
        return toHeaterReading(wire as HeaterStateResponse);
      case "sensor":
        return toSensorReading(wire as TemperatureStateResponse);
      default:
        console.warn(`[temperatureMapper] Unknown temperature type received: ${wire.type}`);
        return null;
    }
  }

  // 2. Legacy fallback: Duck-typing for older payloads that don't have a `type`
  const isHeater = "target" in wire && wire.target !== undefined && wire.target !== null;
  if (isHeater) {
    return toHeaterReading(wire as HeaterStateResponse);
  }
  
  return toSensorReading(wire as TemperatureStateResponse);
}

function toHeaterReading(wire: HeaterStateResponse | Record<string, any>): HeaterReading {
  return new HeaterReading({
    id: wire.tool_id,
    actualCelsius: Number(wire.actual) || 0,
    targetCelsius: Number(wire.target) || 0,
    minTemp: Number.isFinite(Number(wire.min_temp)) ? Number(wire.min_temp) : null,
    maxTemp: Number.isFinite(Number(wire.max_temp)) ? Number(wire.max_temp) : null,
  });
}

function toSensorReading(wire: TemperatureStateResponse | Record<string, any>): SensorReading {
  return new SensorReading({
    id: wire.tool_id,
    actualCelsius: Number(wire.actual) || 0,
  });
}

/**
 * Convert the snapshot's `sensors` dict into a `ReadingSet`.
 */
export function toReadingSet(dict: Record<string, AnyTemperatureWire | Record<string, any>> | null | undefined): ReadingSet {
  if (!dict || typeof dict !== "object") {
    return new ReadingSet([]);
  }
  
  const readings: AnyReading[] = [];
  for (const wire of Object.values(dict)) {
    const r = toReading(wire);
    if (r) readings.push(r);
  }
  
  return new ReadingSet(readings);
}

/**
 * Build the wire payload for the legacy temperature setter. Kept
 * here so the router can hand it off without knowing the wire shape.
 */
export function toLegacySetTargetRequest(sensorName: string, target: number): Record<string, unknown> {
  return { sensor_name: sensorName, target };
}

/**
 * Build the wire payload for the tools heater setter (the live
 * endpoint). New code should prefer this over the legacy one.
 */
export function toHeaterSetTargetRequest(toolId: string, target: number): { tool_id: string; target: number } {
  return { tool_id: toolId, target };
}