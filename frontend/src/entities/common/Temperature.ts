// Temperature value object. ES6 class with a getter for formatted
// display + a ``clampTo`` helper that respects hardware bounds.
//
// Construction is intentionally cheap (no defensive cloning) — the
// mapper layer owns validation. Treat the instance as immutable:
// the class is not frozen to keep the getter ergonomic, but never
// mutate ``_celsius`` from outside.

import { TemperatureUnit } from "./Unit";

const KELVIN_OFFSET = 273.15;

export class Temperature {
  /**
   * @param {number} celsius Raw value in degrees Celsius.
   */
  constructor(celsius) {
    if (typeof celsius !== "number" || Number.isNaN(celsius)) {
      this._celsius = 0;
    } else {
      this._celsius = celsius;
    }
  }

  /** Raw Celsius value. */
  get celsius() {
    return this._celsius;
  }

  /** Formatted for display in the active unit (rounded to 2 dp). */
  formatIn(unit) {
    if (!isTemperatureUnit(unit)) {
      return this._celsius.toFixed(2);
    }
    const v = unit === TemperatureUnit.KELVIN ? this._celsius + KELVIN_OFFSET : this._celsius;
    return v.toFixed(2);
  }

  /** Plain-number representation in the active unit (no rounding). */
  toUnit(unit) {
    if (unit === TemperatureUnit.KELVIN) {
      return this._celsius + KELVIN_OFFSET;
    }
    return this._celsius;
  }

  /** Convenience: ``Number.isFinite`` on the underlying raw value. */
  isFinite() {
    return Number.isFinite(this._celsius);
  }

  /**
   * Clamp this value to ``[min, max]``. Returns a **new** instance;
   * the original is untouched. ``null`` / ``undefined`` bounds are
   * treated as unbounded on that side.
   *
   * @param {number|null|undefined} min
   * @param {number|null|undefined} max
   * @returns {Temperature}
   */
  clampTo(min, max) {
    let v = this._celsius;
    if (typeof min === "number" && Number.isFinite(min) && v < min) v = min;
    if (typeof max === "number" && Number.isFinite(max) && v > max) v = max;
    return v === this._celsius ? this : new Temperature(v);
  }
}

export { KELVIN_OFFSET };
