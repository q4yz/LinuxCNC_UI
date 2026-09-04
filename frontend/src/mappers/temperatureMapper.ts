import { HeaterReading } from "../entities/temperature";
import { SensorReading } from "../entities/temperature";
import { ReadingSet, type AnyReading } from "../entities/temperature/ReadingSet";
// Type-only import — see SpindleDigital.ts for the strip-types rationale.
import type {HeaterStateResponse, TemperatureStateResponse} from "../../generated/api";



// The union of valid temperature wire shapes
export type AnyTemperatureWire = HeaterStateResponse | TemperatureStateResponse;

/**
 * Convert a single wire entry into the appropriate entity.
 * Uses the explicit `type` field discriminator.
 */
export function toReading(wire: unknown): AnyReading | null {
  if (!wire || typeof wire !== "object") return null;
  const w = wire as Record<string, unknown>;
  if (typeof w.id !== "string" || w.id.length === 0) return null;

  // 1. Primary path: Use the explicit type discriminator
  if ("type" in w) {
    switch (w.type) {
      case "heater":
        return toHeaterReading(w);
      case "sensor":
        return toSensorReading(w);
      default:
        console.warn(`[temperatureMapper] Unknown temperature type received: ${String(w.type)}`);
        return null;
    }
  }

  // 2. Legacy fallback: Duck-typing for older payloads that don't have a `type`
  const isHeater = "target" in w && w.target !== undefined && w.target !== null;
  if (isHeater) {
    return toHeaterReading(w);
  }

  return toSensorReading(w);
}

function toHeaterReading(wire: Record<string, unknown>): HeaterReading {
  return new HeaterReading({
    id: wire.id as string,
    actualCelsius: Number(wire.actual) || 0,
    targetCelsius: Number(wire.target) || 0,
    minTemp: Number.isFinite(Number(wire.min_temp)) ? Number(wire.min_temp) : null,
    maxTemp: Number.isFinite(Number(wire.max_temp)) ? Number(wire.max_temp) : null,
  });
}

function toSensorReading(wire: Record<string, unknown>): SensorReading {
  return new SensorReading({
    id: wire.id as string,
    actualCelsius: Number(wire.actual) || 0,
  });
}

/**
 * Convert the snapshot's `sensors` dict into a `ReadingSet`.
 */
export function toReadingSet(dict: unknown): ReadingSet {
  if (!dict || typeof dict !== "object") {
    return new ReadingSet([]);
  }

  const readings: AnyReading[] = [];
  for (const wire of Object.values(dict as Record<string, unknown>)) {
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
export function toHeaterSetTargetRequest(toolId: string, target: number): { id: string; target: number } {
  return { id: toolId, target };
}