// Public surface of the central UI settings.
//
// Define settings in ``settings/definitions/*`` (eagerly imported by
// ``main.ts``), import the instance where you need it:
//
//   import { estopDisablesPower } from "../settings/definitions/machine";
//   if (estopDisablesPower.value) { ... }

export { BaseSetting, type SettingOptions } from "./core/BaseSetting";
export { settingsRegistry } from "./core/settingsRegistry";
export { CheckboxSetting } from "./types/CheckboxSetting";
export { NumberSetting, type NumberBounds } from "./types/NumberSetting";
export { RangeSetting } from "./types/RangeSetting";
export { SelectSetting, type SelectOption } from "./types/SelectSetting";
export { TextSetting, type TextConstraints } from "./types/TextSetting";
