// Temperature unit enum. Frozen; consumers use === comparison.
//
// Kept tiny on purpose: the only consumers today are the
// temperature module's display unit toggle (the frontend converts
// °C ↔ K at the edge) and the chart Y-axis label.

// Erasable ``as const`` object (not a TS ``enum``) so the runtime
// strip-types loader (``node --experimental-strip-types``) can load
// this module without a transform pass.
export const TemperatureUnit = {
  CELSIUS: "C",
  KELVIN: "K",
} as const;
export type TemperatureUnit = (typeof TemperatureUnit)[keyof typeof TemperatureUnit];

export const TEMPERATURE_UNITS = Object.freeze(
  Object.values(TemperatureUnit),
);

export function isTemperatureUnit(value: unknown): value is TemperatureUnit {
  return TEMPERATURE_UNITS.includes(value as TemperatureUnit);
}
