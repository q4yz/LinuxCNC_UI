// Axis entity. Mirrors the ``AxisStateResponse`` Pydantic shape
// emitted by the base-thread snapshot endpoint.
//
// Identified by a string ``id`` carrying the canonical LinuxCNC
// letter (``x``, ``y``, ``z``, ``a``, ...). The numeric ``minLimit``
// and ``maxLimit`` travel with every axis so the dashboard can
// paint a wireframe limits box from the same payload that drives
// the jog / homing controls — no second fetch of ``hardware.json``
// is needed in the frontend.

export interface AxisStateParams {
  id?: string;
  jointNumbers?: number[];
  minLimit?: number;
  maxLimit?: number;
}

export class AxisState {
  private readonly _id: string;
  private readonly _jointNumbers: number[];
  private readonly _minLimit: number;
  private readonly _maxLimit: number;

  constructor({
    id = "",
    jointNumbers = [],
    minLimit = 0,
    maxLimit = 0,
  }: AxisStateParams = {}) {
    this._id = typeof id === "string" ? id.toLowerCase() : "";
    this._jointNumbers = Array.isArray(jointNumbers)
      ? jointNumbers.filter((n) => Number.isFinite(n)).map((n) => Number(n))
      : [];
    this._minLimit = Number.isFinite(minLimit) ? Number(minLimit) : 0;
    this._maxLimit = Number.isFinite(maxLimit) ? Number(maxLimit) : 0;
  }

  get id(): string {
    return this._id;
  }

  get jointNumbers(): number[] {
    return [...this._jointNumbers];
  }

  get minLimit(): number {
    return this._minLimit;
  }

  get maxLimit(): number {
    return this._maxLimit;
  }
}