// Speed override entity. Mirrors ``SpeedOverrideResponse`` from the
// base-thread snapshot (1 Hz): what LinuxCNC actually applies, read back
// from its status channel — not what the UI last requested.
//
//   * ``feedOverride`` — ``stat.feedrate`` as a fraction (1.0 = 100 %).
//   * ``maxVelocity``  — ``stat.max_velocity``, the absolute speed cap
//                        in mm/s.
//
// ``null`` = not reported (LinuxCNC offline / not polled yet) — never a
// guessed 100 % or speed. The ``...Percent`` / ``...MmPerMin`` getters
// are the units the speed sliders work in.

export interface SpeedOverrideParams {
  feedOverride?: number | null;
  maxVelocity?: number | null;
}

const finiteOrNull = (value: unknown, { positive }: { positive: boolean }): number | null => {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return null;
  if (positive && value === 0) return null;
  return value;
};

export class SpeedOverride {
  private readonly _feedOverride: number | null;
  private readonly _maxVelocity: number | null;

  constructor({ feedOverride = null, maxVelocity = null }: SpeedOverrideParams = {}) {
    // 0 % is a legal override (feed hold); a 0 speed cap is not a setting.
    this._feedOverride = finiteOrNull(feedOverride, { positive: false });
    this._maxVelocity = finiteOrNull(maxVelocity, { positive: true });
  }

  /** Feed override as a fraction (1.0 = 100 %), or ``null`` when unknown. */
  get feedOverride(): number | null {
    return this._feedOverride;
  }

  /** Feed override in percent (100 = 100 %), or ``null`` when unknown. */
  get feedOverridePercent(): number | null {
    return this._feedOverride === null ? null : Math.round(this._feedOverride * 1000) / 10;
  }

  /** Absolute speed cap in mm/s, or ``null`` when unknown. */
  get maxVelocity(): number | null {
    return this._maxVelocity;
  }

  /** Absolute speed cap in mm/min, or ``null`` when unknown. */
  get maxVelocityMmPerMin(): number | null {
    return this._maxVelocity === null ? null : Math.round(this._maxVelocity * 60 * 10) / 10;
  }
}
