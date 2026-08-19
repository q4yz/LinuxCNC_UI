// Axis-position value object. Wraps the x/y/z triplet coming off
// the servo-thread WebSocket so consumers don't have to remember
// which axis is which.
//
// Units are millimetres; the backend always reports mm regardless
// of operator preference.

export const AXIS_NAMES = ["x", "y", "z"] as const;

export type AxisNameType = typeof AXIS_NAMES[number];

export interface AxisPositionParams {
  x?: number;
  y?: number;
  z?: number;
  unit?: string;
}

export class AxisPosition {
  private readonly _x: number;
  private readonly _y: number;
  private readonly _z: number;
  private readonly _unit: string;

  constructor({ x = 0, y = 0, z = 0, unit = "mm" }: AxisPositionParams = {}) {
    this._x = Number.isFinite(x) ? x : 0;
    this._y = Number.isFinite(y) ? y : 0;
    this._z = Number.isFinite(z) ? z : 0;
    this._unit = typeof unit === "string" ? unit : "mm";
  }

  get x(): number {
    return this._x;
  }

  get y(): number {
    return this._y;
  }

  get z(): number {
    return this._z;
  }

  get unit(): string {
    return this._unit;
  }

  /** Return the position as ``[x, y, z]`` (handy for the DRO). */
  toArray(): [number, number, number] {
    return [this._x, this._y, this._z];
  }

  /** Map ``x`` / ``y`` / ``z`` to the canonical letter labels. */
  toLabeledMap(): { X: number; Y: number; Z: number } {
    return { X: this._x, Y: this._y, Z: this._z };
  }
}