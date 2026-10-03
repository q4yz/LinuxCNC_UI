import { defineAsyncComponent, type Component } from "vue";
import { BaseSetting, type SettingOptions } from "../core/BaseSetting";

// Lazy: the editor .vue is only loaded when the Settings view renders it.
const SettingSelect = defineAsyncComponent(() => import("../components/SettingSelect.vue"));

export interface SelectOption<V extends string | number> {
  value: V;
  label: string;
}

/** One-of-N setting, edited with ``BaseSelect``. */
export class SelectSetting<V extends string | number = string> extends BaseSetting<V> {
  constructor(
    category: string,
    label: string,
    key: string,
    defaultValue: V,
    choices: SelectOption<V>[],
    options: SettingOptions = {},
  ) {
    super(category, label, key, defaultValue, { ...options, config: { choices } });
  }

  get type(): string {
    return "select";
  }

  get component(): Component {
    return SettingSelect;
  }

  get choices(): SelectOption<V>[] {
    return (this.config.choices as SelectOption<V>[]) ?? [];
  }

  validate(raw: unknown): V | undefined {
    const match = this.choices.find((c) => c.value === raw);
    return match ? match.value : undefined;
  }
}
