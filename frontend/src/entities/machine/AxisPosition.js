// Axis-position value object. Wraps the x/y/z triplet coming off
// the servo-thread WebSocket so consumers don't have to remember
// which axis is which.
//
// Units are millimetres; the backend always reports mm regardless
// of operator preference.

export const AXIS_NAMES = Object.freeze(["x", "y", "z"]);

export class AxisPosition {
  /**
   * @param {object} params
   * @param {number} [params.x]
   * @param {number} [params.y]
   * @param {number} [params.z]
   * @param {string} [params.unit]
   */
  constructor({ x = 0, y = 0, z = 0, unit = "mm" } = {}) {
    this._x = Number.isFinite(x) ? x : 0;
    this._y = Number.isFinite(y) ? y : 0;
    this._z = Number.isFinite(z) ? z : 0;
    this._unit = typeof unit === "string" ? unit : "mm";
  }

  get x() {
    return this._x;
  }

  get y() {
    return this._y;
  }

  get z() {
    return this._z;
  }

  get unit() {
    return this._unit;
  }

  /** Return the position as ``[x, y, z]`` (handy for the DRO). */
  toArray() {
    return [this._x, this._y, this._z];
  }

  /** Map ``x`` / ``y`` / ``z`` to the canonical letter labels. */
  toLabeledMap() {
    return { X: this._x, Y: this._y, Z: this._z };
  }
}
