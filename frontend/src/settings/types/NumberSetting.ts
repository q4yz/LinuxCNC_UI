import { defineAsyncComponent, type Component } from "vue";
import { BaseSetting, type SettingOptions } from "../core/BaseSetting";

// Lazy: the editor .vue is only loaded when the Settings view renders it.
const SettingNumber = defineAsyncComponent(() => import("../components/SettingNumber.vue"));

export interface NumberBounds {
  min?: number;
  max?: number;
  step?: number;
  /** Shown next to the input, e.g. ``"mm/s"``. */
  unit?: string;
}

/** Numeric setting with optional bounds, edited with a number input. */
export class NumberSetting extends BaseSetting<number> {
  constructor(
    category: string,
    label: string,
    key: string,
    defaultValue: number,
    bounds: NumberBounds = {},
    options: SettingOptions = {},
  ) {
    super(category, label, key, defaultValue, { ...options, config: { ...bounds } });
  }

  get type(): string {
    return "number";
  }

  get component(): Component {
    return SettingNumber;
  }

  get bounds(): NumberBounds {
    return this.config as NumberBounds;
  }

  validate(raw: unknown): number | undefined {
    const value = typeof raw === "number" ? raw : typeof raw === "string" && raw.trim() !== "" ? Number(raw) : NaN;
    if (!Number.isFinite(value)) return undefined;
    const { min, max } = this.bounds;
    if (min !== undefined && value < min) return undefined;
    if (max !== undefined && value > max) return undefined;
    return value;
  }
}
