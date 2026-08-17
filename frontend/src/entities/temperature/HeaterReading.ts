export interface HeaterReadingParams {
  id: string | EntityId;
  actualCelsius: number;
  targetCelsius?: number;
  minTemp?: number | null;
  maxTemp?: number | null;
}

export class HeaterReading {
  private readonly _id: EntityId;
  private readonly _actual: Temperature;
  private readonly _target: Temperature;
  private readonly _min: number | null;
  private readonly _max: number | null;

  constructor({ 
    id, 
    actualCelsius, 
    targetCelsius = 0, 
    minTemp = null, 
    maxTemp = null 
  }: HeaterReadingParams) {
    this._id = id instanceof EntityId ? id : new EntityId(id, "heater");
    this._actual = new Temperature(actualCelsius);
    this._target = new Temperature(targetCelsius);
    this._min = typeof minTemp === "number" && Number.isFinite(minTemp) ? minTemp : null;
    this._max = typeof maxTemp === "number" && Number.isFinite(maxTemp) ? maxTemp : null;
  }

  get id(): string {
    return this._id.value;
  }

  get entityId(): EntityId {
    return this._id;
  }

  get actualCelsius(): number {
    return this._actual.celsius;
  }

  get targetCelsius(): number {
    return this._target.celsius;
  }

  get minTemp(): number | null {
    return this._min;
  }

  get maxTemp(): number | null {
    return this._max;
  }

  get actual(): Temperature {
    return this._actual;
  }

  get target(): Temperature {
    return this._target;
  }

  get isControllable(): boolean {
    return true;
  }

  /** `true` iff both `minTemp` and `maxTemp` are finite numbers. */
  hasBounds(): boolean {
    return this._min !== null && this._max !== null;
  }

  /** Human-friendly range string, e.g. `"0 – 300 °C"`. */
  boundsLabel(unit: TemperatureUnit = TemperatureUnit.CELSIUS): string {
    if (!this.hasBounds()) {
      return "";
    }
    const suffix = unit === TemperatureUnit.KELVIN ? "K" : "°C";
    return `${this._min} – ${this._max} ${suffix}`;
  }

  /**
   * Clamp `value` (in Celsius) to the heater's hardware bounds.
   * Returns a **new** `Temperature` instance; the original is
   * untouched. `value` outside the bounds is snapped to the bound.
   */
  clampCelsius(value: number): Temperature {
    // Note: Assuming Temperature.clampTo can handle `number | null` bounds.
    return new Temperature(value).clampTo(this._min, this._max);
  }

  formatActual(unit: TemperatureUnit): string {
    return this._actual.formatIn(unit);
  }

  formatTarget(unit: TemperatureUnit): string {
    return this._target.formatIn(unit);
  }

  actualInUnit(unit: TemperatureUnit): number {
    return this._actual.toUnit(unit);
  }

  targetInUnit(unit: TemperatureUnit): number {
    return this._target.toUnit(unit);
  }
}