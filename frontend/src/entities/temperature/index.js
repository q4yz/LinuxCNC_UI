// Re-exports so callers can ``import { SensorReading, HeaterReading,
// ReadingSet } from "../entities/temperature/index.js";`` instead
// of remembering the per-file paths.

export { SensorReading, HeaterReading } from "./Reading.js";
export { ReadingSet } from "./ReadingSet.js";
