// Temperature display settings (conversion is display-only; the backend
// always reports °C).
import { TemperatureUnit } from "../../entities/common/Unit";
import { SelectSetting } from "../types/SelectSetting";
import { SensorColorsSetting } from "../types/SensorColorsSetting";

export const temperatureUnit = new SelectSetting<TemperatureUnit>(
  "Temperature",
  "Display unit",
  "temperature.unit",
  TemperatureUnit.CELSIUS,
  [
    { value: TemperatureUnit.CELSIUS, label: "°C" },
    { value: TemperatureUnit.FAHRENHEIT, label: "°F" },
    { value: TemperatureUnit.KELVIN, label: "K" },
  ],
  { description: "Temperature card: chart axis, readings and target boxes. Display-only: °F = °C × 9/5 + 32, K = °C + 273.15.", order: 0 },
);

export const sensorColors = new SensorColorsSetting(
  "Temperature",
  "Sensor colours",
  "temperature.sensor_colors",
  {},
  { description: "Chart series and swatch colour per sensor.", order: 1 },
);
