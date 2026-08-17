// Temperature domain entities.
//
// Two flavours of reading come off the backend base-thread snapshot:
//   - ``SensorReading``: read-only, only carries the actual temp.
//   - ``HeaterReading``: controllable, carries target + min/max too.
//
// The discriminator lives in the mapper (``wire.target !== undefined``)
// so the entity layer never has to look at wire-shape details.

import { EntityId } from "../common/EntityId.js";
import { Temperature } from "../common/Temperature.js";
import { TemperatureUnit } from "../common/Unit.js";

export class SensorReading {
  /**
   * @param {object} params
   * @param {string|EntityId} params.id
   * @param {number} params.actualCelsius
   */
  constructor({ id, actualCelsius }) {
    this._id = id instanceof EntityId ? id : new EntityId(id, "sensor");
    this._actual = new Temperature(actualCelsius);
  }

  get id() {
    return this._id.value;
  }

  /** Typed id (escape hatch when consumers need it). */
  get entityId() {
    return this._id;
  }

  get actualCelsius() {
    return this._actual.celsius;
  }

  /** Read-only — sensors are never directly targetable. */
  get isControllable() {
    return false;
  }

  /** Convenience Temperature handle. */
  get actual() {
    return this._actual;
  }

  /** Format the actual temp for the active display unit. */
  formatActual(unit) {
    return this._actual.formatIn(unit);
  }

  /** Plain number in the active unit. */
  actualInUnit(unit) {
    return this._actual.toUnit(unit);
  }
}

export class HeaterReading {
  /**
   * @param {object} params
   * @param {string|EntityId} params.id
   * @param {number} params.actualCelsius
   * @param {number} [params.targetCelsius]
   * @param {number|null} [params.minTemp]
   * @param {number|null} [params.maxTemp]
   */
  constructor({ id, actualCelsius, targetCelsius = 0, minTemp = null, maxTemp = null }) {
    this._id = id instanceof EntityId ? id : new EntityId(id, "heater");
    this._actual = new Temperature(actualCelsius);
    this._target = new Temperature(targetCelsius);
    this._min = typeof minTemp === "number" && Number.isFinite(minTemp) ? minTemp : null;
    this._max = typeof maxTemp === "number" && Number.isFinite(maxTemp) ? maxTemp : null;
  }

  get id() {
    return this._id.value;
  }

  get entityId() {
    return this._id;
  }

  get actualCelsius() {
    return this._actual.celsius;
  }

  get targetCelsius() {
    return this._target.celsius;
  }

  get minTemp() {
    return this._min;
  }

  get maxTemp() {
    return this._max;
  }

  get actual() {
    return this._actual;
  }

  get target() {
    return this._target;
  }

  get isControllable() {
    return true;
  }

  /** ``true`` iff both ``minTemp`` and ``maxTemp`` are finite numbers. */
  hasBounds() {
    return this._min !== null && this._max !== null;
  }

  /** Human-friendly range string, e.g. ``"0 – 300 °C"``. */
  boundsLabel(unit = TemperatureUnit.CELSIUS) {
    if (!this.hasBounds()) {
      return "";
    }
    const suffix = unit === TemperatureUnit.KELVIN ? "K" : "°C";
    return `${this._min} – ${this._max} ${suffix}`;
  }

  /**
   * Clamp ``value`` (in Celsius) to the heater's hardware bounds.
   * Returns a **new** ``Temperature`` instance; the original is
   * untouched. ``value`` outside the bounds is snapped to the bound.
   */
  clampCelsius(value) {
    return new Temperature(value).clampTo(this._min, this._max);
  }

  formatActual(unit) {
    return this._actual.formatIn(unit);
  }

  formatTarget(unit) {
    return this._target.formatIn(unit);
  }

  actualInUnit(unit) {
    return this._actual.toUnit(unit);
  }

  targetInUnit(unit) {
    return this._target.toUnit(unit);
  }
}
