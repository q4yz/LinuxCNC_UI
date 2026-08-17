// Temperature unit enum. Frozen; consumers use === comparison.
//
// Kept tiny on purpose: the only consumers today are the
// temperature module's display unit toggle (the frontend converts
// °C ↔ K at the edge) and the chart Y-axis label.

export enum TemperatureUnit {
  CELSIUS = "C",
  KELVIN = "K",
}

export const TEMPERATURE_UNITS = Object.freeze(
  Object.values(TemperatureUnit),
);

export function isTemperatureUnit(value) {
  return TEMPERATURE_UNITS.includes(value);
}
