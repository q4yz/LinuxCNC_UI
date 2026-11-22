import type { Component } from "vue";
import { BaseSetting, type SettingOptions } from "../core/BaseSetting";

/**
 * Not a stored value: a panel shown in its Settings tab like a setting
 * (the Assistant's connection info, its API key form, which keep their own
 * data elsewhere). ``component`` gets ``:setting`` like every editor.
 */
export class PanelSetting extends BaseSetting<null> {
  private readonly _component: Component;

  constructor(category: string, label: string, key: string, component: Component, options: SettingOptions = {}) {
    super(category, label, key, null, options);
    this._component = component;
  }

  get type(): string {
    return "panel";
  }

  get wide(): boolean {
    return true;
  }

  get component(): Component {
    return this._component;
  }

  validate(): null {
    return null;
  }
}
