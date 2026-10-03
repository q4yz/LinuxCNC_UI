import { defineAsyncComponent, type Component } from "vue";
import { BaseSetting, type SettingOptions } from "../core/BaseSetting";

// Lazy: the editor .vue is only loaded when the Settings view renders it.
const SettingCheckbox = defineAsyncComponent(() => import("../components/SettingCheckbox.vue"));

/** On/off setting, edited with ``BaseCheckbox``. */
export class CheckboxSetting extends BaseSetting<boolean> {
  constructor(category: string, label: string, key: string, defaultValue: boolean, options: SettingOptions = {}) {
    super(category, label, key, defaultValue, options);
  }

  get type(): string {
    return "checkbox";
  }

  get component(): Component {
    return SettingCheckbox;
  }

  validate(raw: unknown): boolean | undefined {
    return typeof raw === "boolean" ? raw : undefined;
  }
}
