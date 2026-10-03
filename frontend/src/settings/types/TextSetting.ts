import { defineAsyncComponent, type Component } from "vue";
import { BaseSetting, type SettingOptions } from "../core/BaseSetting";

// Lazy: the editor .vue is only loaded when the Settings view renders it.
const SettingText = defineAsyncComponent(() => import("../components/SettingText.vue"));

export interface TextConstraints {
  placeholder?: string;
  maxLength?: number;
}

/** Free-text setting, edited with a text input (saved on change). */
export class TextSetting extends BaseSetting<string> {
  constructor(
    category: string,
    label: string,
    key: string,
    defaultValue: string,
    constraints: TextConstraints = {},
    options: SettingOptions = {},
  ) {
    super(category, label, key, defaultValue, { ...options, config: { ...constraints } });
  }

  get type(): string {
    return "text";
  }

  get component(): Component {
    return SettingText;
  }

  get constraints(): TextConstraints {
    return this.config as TextConstraints;
  }

  validate(raw: unknown): string | undefined {
    if (typeof raw !== "string") return undefined;
    const { maxLength } = this.constraints;
    if (maxLength !== undefined && raw.length > maxLength) return undefined;
    return raw;
  }
}
