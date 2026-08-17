// Temperature domain entities.
//
// Two flavours of reading come off the backend base-thread snapshot:
//   - `SensorReading`: read-only, only carries the actual temp.
//   - `HeaterReading`: controllable, carries target + min/max too.
//
// The discriminator lives in the mapper (`wire.target !== undefined`)
// so the entity layer never has to look at wire-shape details.

import { EntityId } from "../common/EntityId";
import { Temperature } from "../common/Temperature";
import { TemperatureUnit } from "../common/Unit";

export interface SensorReadingParams {
  id: string | EntityId;
  actualCelsius: number;
}

export class SensorReading {
  private readonly _id: EntityId;
  private readonly _actual: Temperature;

  constructor({ id, actualCelsius }: SensorReadingParams) {
    this._id = id instanceof EntityId ? id : new EntityId(id, "sensor");
    this._actual = new Temperature(actualCelsius);
  }

  get id(): string {
    return this._id.value;
  }

  /** Typed id (escape hatch when consumers need it). */
  get entityId(): EntityId {
    return this._id;
  }

  get actualCelsius(): number {
    return this._actual.celsius;
  }

  /** Read-only — sensors are never directly targetable. */
  get isControllable(): boolean {
    return false;
  }

  /** Convenience Temperature handle. */
  get actual(): Temperature {
    return this._actual;
  }

  /** Format the actual temp for the active display unit. */
  formatActual(unit: TemperatureUnit): string {
    return this._actual.formatIn(unit);
  }

  /** Plain number in the active unit. */
  actualInUnit(unit: TemperatureUnit): number {
    return this._actual.toUnit(unit);
  }
}