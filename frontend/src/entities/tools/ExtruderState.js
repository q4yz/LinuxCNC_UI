// Extruder state entity. Wraps the wire shape that comes off the
// tools overlay in the base-thread snapshot (``HeaterStateResponse``
// with a nested ``heater`` field per the backend's flattening
// logic). The mapper is responsible for un-nesting the heater
// payload back into the inner ``HeaterReading`` — see
// ``mappers/toolsMapper.js``.

import { EntityId } from "../common/EntityId.js";
import { HeaterReading } from "../temperature/Reading.js";

export class ExtruderState {
  /**
   * @param {object} params
   * @param {string|EntityId} params.id
   * @param {number} [params.position]
   * @param {HeaterReading|null} [params.heater]
   */
  constructor({ id, position = 0, heater = null } = {}) {
    this._id = id instanceof EntityId ? id : new EntityId(id, "extruder");
    this._position = Number.isFinite(position) ? position : 0;
    this._heater = heater instanceof HeaterReading ? heater : null;
  }

  get id() {
    return this._id.value;
  }

  get entityId() {
    return this._id;
  }

  get position() {
    return this._position;
  }

  get heater() {
    return this._heater;
  }

  /** Extruders are always controllable (via the heater). */
  get isControllable() {
    return this._heater !== null;
  }
}
