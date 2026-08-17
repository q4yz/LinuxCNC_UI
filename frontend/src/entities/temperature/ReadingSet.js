// Collection wrapper for the discriminated set of temperature
// readings coming off the base-thread snapshot. Hides the "dict by
// id" detail from consumers; ``get(id)``, ``heaters()``,
// ``sensors()`` and ``all()`` are the only surface.

import { HeaterReading, SensorReading } from "./Reading.js";

export class ReadingSet {
  /**
   * @param {Array<SensorReading|HeaterReading>} readings
   */
  constructor(readings = []) {
    /** @type {Map<string, SensorReading|HeaterReading>} */
    this._byId = new Map();
    /** @type {SensorReading[]} */
    this._sensors = [];
    /** @type {HeaterReading[]} */
    this._heaters = [];
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
  get size() {
    return this._byId.size;
  }

  /** Lookup by id, or ``undefined`` if absent. */
  get(id) {
    return this._byId.get(id);
  }

  /** True iff the id exists in the set. */
  has(id) {
    return this._byId.has(id);
  }

  /** Iterable of every reading. */
  all() {
    return Array.from(this._byId.values());
  }

  /** Iterable of just the read-only sensors. */
  sensors() {
    return this._sensors.slice();
  }

  /** Iterable of just the controllable heaters. */
  heaters() {
    return this._heaters.slice();
  }

  /** Convenience: list of all ids. */
  ids() {
    return Array.from(this._byId.keys());
  }

  forEach(callback, thisArg) {
    this._byId.forEach((v, k) => callback.call(thisArg, v, k, this));
  }
}
