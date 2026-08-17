// Spindle state entity. Wraps the wire shape from the base-thread
// snapshot / ``GET /api/v1/modules/tools/spindle/{id}``.
//
// Direction is modelled as a plain string (``"forward"`` /
// ``"backward"`` / ``"idle"``) — the backend's
// ``SpindleDigitalStateResponse.state`` field is already
// string-typed; mapping is a no-op pass-through.

import { EntityId } from "../common/EntityId.js";

export const SPINDLE_DIRECTIONS = Object.freeze([
  "forward",
  "backward",
  "idle",
]);

export class SpindleState {
  /**
   * @param {object} params
   * @param {string|EntityId} params.id
   * @param {"forward"|"backward"|"idle"} params.direction
   * @param {number} [params.actualRpm]
   * @param {boolean} [params.isConnected]
   * @param {number} [params.errorCount]
   * @param {string} [params.lastError]
   * @param {boolean} [params.atSpeed]
   * @param {number} [params.minRpm]
   * @param {number} [params.maxRpm]
   */
  constructor({
    id,
    direction = "idle",
    actualRpm = 0,
    isConnected = false,
    errorCount = 0,
    lastError = "",
    atSpeed = false,
    minRpm = 0,
    maxRpm = 24000,
  } = {}) {
    this._id = id instanceof EntityId ? id : new EntityId(id, "spindle");
    this._direction = SPINDLE_DIRECTIONS.includes(direction) ? direction : "idle";
    this._actualRpm = Number.isFinite(actualRpm) ? actualRpm : 0;
    this._isConnected = Boolean(isConnected);
    this._errorCount = Number.isFinite(errorCount) ? errorCount : 0;
    this._lastError = lastError || "";
    this._atSpeed = Boolean(atSpeed);
    this._minRpm = Number.isFinite(minRpm) ? minRpm : 0;
    this._maxRpm = Number.isFinite(maxRpm) ? maxRpm : 24000;
  }

  get id() {
    return this._id.value;
  }

  get entityId() {
    return this._id;
  }

  get direction() {
    return this._direction;
  }

  get actualRpm() {
    return this._actualRpm;
  }

  get isConnected() {
    return this._isConnected;
  }

  get errorCount() {
    return this._errorCount;
  }

  get lastError() {
    return this._lastError;
  }

  get atSpeed() {
    return this._atSpeed;
  }

  get minRpm() {
    return this._minRpm;
  }

  get maxRpm() {
    return this._maxRpm;
  }

  get isRunning() {
    return this._direction !== "idle";
  }

  /** Percentage of max rpm (for the gauge gradient). */
  fractionOfMax() {
    if (this._maxRpm <= 0) return 0;
    return Math.max(0, Math.min(1, this._actualRpm / this._maxRpm));
  }
}
