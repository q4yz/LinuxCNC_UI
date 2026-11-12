// Temperature display units (`src/entities/common/Unit.ts`): °C / °F / K.
// The backend always reports and takes °C; the frontend converts at the edge.
//
// Run with: ``node --experimental-strip-types --test frontend/tests/test-temperature-units.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { TemperatureUnit, celsiusTo, temperatureSymbol, toCelsius } from "../src/entities/common/Unit";
import { Temperature } from "../src/entities/common/Temperature";

test("°C to the display unit", () => {
  assert.equal(celsiusTo(100, TemperatureUnit.CELSIUS), 100);
  assert.equal(celsiusTo(100, TemperatureUnit.FAHRENHEIT), 212);
  assert.equal(celsiusTo(0, TemperatureUnit.FAHRENHEIT), 32);
  assert.equal(celsiusTo(0, TemperatureUnit.KELVIN), 273.15);
});

test("a typed target back to °C", () => {
  assert.equal(toCelsius(212, TemperatureUnit.FAHRENHEIT), 100);
  assert.equal(toCelsius(428, TemperatureUnit.FAHRENHEIT), 220);
  assert.equal(toCelsius(493.15, TemperatureUnit.KELVIN), 220);
  assert.equal(toCelsius(220, TemperatureUnit.CELSIUS), 220);
  for (const unit of Object.values(TemperatureUnit)) {
    assert.ok(Math.abs(toCelsius(celsiusTo(215.5, unit), unit) - 215.5) < 1e-9, unit);
  }
});

test("symbols", () => {
  assert.equal(temperatureSymbol(TemperatureUnit.CELSIUS), "°C");
  assert.equal(temperatureSymbol(TemperatureUnit.FAHRENHEIT), "°F");
  assert.equal(temperatureSymbol(TemperatureUnit.KELVIN), "K");
});

test("Temperature formats in °F", () => {
  assert.equal(new Temperature(60).formatIn(TemperatureUnit.FAHRENHEIT), "140.00");
  assert.equal(new Temperature(60).toUnit(TemperatureUnit.FAHRENHEIT), 140);
});
