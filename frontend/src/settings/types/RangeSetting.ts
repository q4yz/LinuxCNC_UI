import { defineAsyncComponent, type Component } from "vue";
import type { SettingOptions } from "../core/BaseSetting";
import { NumberSetting } from "./NumberSetting";

// Lazy: the editor .vue is only loaded when the Settings view renders it.
const SettingRange = defineAsyncComponent(() => import("../components/SettingRange.vue"));

/** Bounded numeric setting edited with a slider (``BaseRange``). */
export class RangeSetting extends NumberSetting {
  constructor(
    category: string,
    label: string,
    key: string,
    defaultValue: number,
    bounds: { min: number; max: number; step?: number; unit?: string },
    options: SettingOptions = {},
  ) {
    super(category, label, key, defaultValue, bounds, options);
  }

  get type(): string {
    return "range";
  }

  get component(): Component {
    return SettingRange;
  }
}
