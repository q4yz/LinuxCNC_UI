// Axis entity. Mirrors the ``AxisStateResponse`` Pydantic shape
// emitted by the base-thread snapshot endpoint.
//
// Identified by a string ``id`` carrying the canonical LinuxCNC
// letter (``x``, ``y``, ``z``, ``a``, ...). The numeric ``minLimit``
// and ``maxLimit`` travel with every axis so the dashboard can
// paint a wireframe limits box from the same payload that drives
// the jog / homing controls — no second fetch of ``hardware.json``
// is needed in the frontend.
//
// ``maxVelocity`` (mm/s) / ``maxAcceleration`` (mm/s²) are the
// machine's own axis limits — the values ``machine.ini``'s
// ``[AXIS_*] MAX_VELOCITY``/``MAX_ACCELERATION`` carry. ``null`` when
// the machine config doesn't provide them; never defaulted, since
// speed sliders are sized from them.

export interface AxisStateParams {
  id?: string;
  jointNumbers?: number[];
  minLimit?: number;
  maxLimit?: number;
  maxVelocity?: number | null;
  maxAcceleration?: number | null;
}

/** A limit is only real when it is a positive, finite number. */
const positiveOrNull = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;

export class AxisState {
  private readonly _id: string;
  private readonly _jointNumbers: number[];
  private readonly _minLimit: number;
  private readonly _maxLimit: number;
  private readonly _maxVelocity: number | null;
  private readonly _maxAcceleration: number | null;

  constructor({
    id = "",
    jointNumbers = [],
    minLimit = 0,
    maxLimit = 0,
    maxVelocity = null,
    maxAcceleration = null,
  }: AxisStateParams = {}) {
    this._id = typeof id === "string" ? id.toLowerCase() : "";
    this._jointNumbers = Array.isArray(jointNumbers)
      ? jointNumbers.filter((n) => Number.isFinite(n)).map((n) => Number(n))
      : [];
    this._minLimit = Number.isFinite(minLimit) ? Number(minLimit) : 0;
    this._maxLimit = Number.isFinite(maxLimit) ? Number(maxLimit) : 0;
    this._maxVelocity = positiveOrNull(maxVelocity);
    this._maxAcceleration = positiveOrNull(maxAcceleration);
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

  /** Axis velocity limit in mm/s, or ``null`` when unknown. */
  get maxVelocity(): number | null {
    return this._maxVelocity;
  }

  /** Axis acceleration limit in mm/s², or ``null`` when unknown. */
  get maxAcceleration(): number | null {
    return this._maxAcceleration;
  }
}
