// Tool-list collection. Mirrors ``ReadingSet`` but for the tools
// (spindle / extruder / heater) side of the base-thread snapshot.
//
// The wire shape is a discriminated array (one element per tool
// with a ``type`` discriminator); the mapper produces this.

import { SpindleState } from "./SpindleState.js";
import { ExtruderState } from "./ExtruderState.js";
import { HeaterReading } from "../temperature/Reading.js";

export class ToolList {
  /**
   * @param {Array<SpindleState|ExtruderState|HeaterReading>} tools
   */
  constructor(tools = []) {
    /** @type {Map<string, SpindleState|ExtruderState|HeaterReading>} */
    this._byId = new Map();
    /** @type {SpindleState[]} */
    this._spindles = [];
    /** @type {ExtruderState[]} */
    this._extruders = [];
    /** @type {HeaterReading[]} */
    this._heaters = [];
    for (const t of tools) {
      if (t instanceof SpindleState) this._spindles.push(t);
      else if (t instanceof ExtruderState) this._extruders.push(t);
      else if (t instanceof HeaterReading) this._heaters.push(t);
      else continue;
      this._byId.set(t.id, t);
    }
  }

  get size() {
    return this._byId.size;
  }

  get(id) {
    return this._byId.get(id);
  }

  has(id) {
    return this._byId.has(id);
  }

  all() {
    return Array.from(this._byId.values());
  }

  spindles() {
    return this._spindles.slice();
  }

  extruders() {
    return this._extruders.slice();
  }

  heaters() {
    return this._heaters.slice();
  }

  ids() {
    return Array.from(this._byId.keys());
  }

  forEach(callback, thisArg) {
    this._byId.forEach((v, k) => callback.call(thisArg, v, k, this));
  }
}
