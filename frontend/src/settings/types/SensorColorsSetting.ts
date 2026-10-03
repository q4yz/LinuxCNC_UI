import { defineAsyncComponent, type Component } from "vue";
import { BaseSetting, type SettingOptions } from "../core/BaseSetting";

// Lazy: the editor .vue is only loaded when the Settings view renders it.
const SettingSensorColors = defineAsyncComponent(() => import("../components/SettingSensorColors.vue"));

const HEX = /^#[0-9A-Fa-f]{6}$/;
const SENSOR_NAME = /^[a-z][a-z0-9_-]{0,40}$/;

/** Sensor id → chart/swatch colour (``#rrggbb``). */
export class SensorColorsSetting extends BaseSetting<Record<string, string>> {
  constructor(category: string, label: string, key: string, defaultValue: Record<string, string>, options: SettingOptions = {}) {
    super(category, label, key, defaultValue, options);
  }

  get type(): string {
    return "sensor-colors";
  }

  get component(): Component {
    return SettingSensorColors;
  }

  /** Drops entries that aren't ``sensor-id: #rrggbb`` instead of rejecting the whole map. */
  validate(raw: unknown): Record<string, string> | undefined {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
    const out: Record<string, string> = {};
    for (const [name, hex] of Object.entries(raw as Record<string, unknown>)) {
      if (SENSOR_NAME.test(name) && typeof hex === "string" && HEX.test(hex)) out[name] = hex;
    }
    return out;
  }

  /** Persist one sensor's colour, keeping the others. */
  setColor(name: string, hex: string) {
    return this.save({ ...(this.value ?? {}), [name]: hex });
  }
}
