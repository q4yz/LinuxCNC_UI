import { HeaterReading, SensorReading } from "./Reading";

export type AnyReading = HeaterReading | SensorReading;

export class ReadingSet {
  private readonly _byId: Map<string, AnyReading> = new Map();
  private readonly _sensors: SensorReading[] = [];
  private readonly _heaters: HeaterReading[] = [];

  constructor(readings: AnyReading[] = []) {
    for (const r of readings) {
      if (r instanceof HeaterReading) {
        this._heaters.push(r);
      } else if (r instanceof SensorReading) {
        this._sensors.push(r);
      } else {
        // Be tolerant of unknown types — skip rather than throw so
        // a future entity class doesn't break the chart.
        continue;
      }
      this._byId.set(r.id, r);
    }
  }

  /** Total count. */
  get size(): number {
    return this._byId.size;
  }

  /** Lookup by id, or `undefined` if absent. */
  get(id: string): AnyReading | undefined {
    return this._byId.get(id);
  }

  /** True iff the id exists in the set. */
  has(id: string): boolean {
    return this._byId.has(id);
  }

  /** Iterable of every reading. */
  all(): AnyReading[] {
    return Array.from(this._byId.values());
  }

  /** Iterable of just the read-only sensors. */
  sensors(): SensorReading[] {
    return [...this._sensors];
  }

  /** Iterable of just the controllable heaters. */
  heaters(): HeaterReading[] {
    return [...this._heaters];
  }

  /** Convenience: list of all ids. */
  ids(): string[] {
    return Array.from(this._byId.keys());
  }

  forEach(
    callback: (value: AnyReading, key: string, map: ReadingSet) => void,
    thisArg?: unknown
  ): void {
    this._byId.forEach((value, key) => {
      callback.call(thisArg, value, key, this);
    });
  }
}