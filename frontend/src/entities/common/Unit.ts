// Temperature unit enum. Frozen; consumers use === comparison.
//
// Kept tiny on purpose: the only consumers today are the
// temperature module's display unit (the backend always reports °C;
// the frontend converts °C ↔ K / °F at the edge, with the helpers
// below) and the chart Y-axis label.

// Erasable ``as const`` object (not a TS ``enum``) so the runtime
// strip-types loader (``node --experimental-strip-types``) can load
// this module without a transform pass.
export const TemperatureUnit = {
  CELSIUS: "C",
  KELVIN: "K",
  FAHRENHEIT: "F",
} as const;
export type TemperatureUnit = (typeof TemperatureUnit)[keyof typeof TemperatureUnit];

export const TEMPERATURE_UNITS = Object.freeze(
  Object.values(TemperatureUnit),
);

export function isTemperatureUnit(value: unknown): value is TemperatureUnit {
  return TEMPERATURE_UNITS.includes(value as TemperatureUnit);
}

const KELVIN_OFFSET = 273.15;

/** A °C reading in ``unit`` (unrounded). */
export function celsiusTo(celsius: number, unit: TemperatureUnit | string): number {
  if (unit === TemperatureUnit.KELVIN) return celsius + KELVIN_OFFSET;
  if (unit === TemperatureUnit.FAHRENHEIT) return celsius * 9 / 5 + 32;
  return celsius;
}

/** A value typed in ``unit`` as °C — what the backend takes. */
export function toCelsius(value: number, unit: TemperatureUnit | string): number {
  if (unit === TemperatureUnit.KELVIN) return value - KELVIN_OFFSET;
  if (unit === TemperatureUnit.FAHRENHEIT) return (value - 32) * 5 / 9;
  return value;
}

/** ``°C`` / ``K`` / ``°F``. */
export function temperatureSymbol(unit: TemperatureUnit | string): string {
  if (unit === TemperatureUnit.KELVIN) return "K";
  if (unit === TemperatureUnit.FAHRENHEIT) return "°F";
  return "°C";
}
