import { defineAsyncComponent, type Component } from "vue";
import { BaseSetting, type SettingOptions } from "../core/BaseSetting";

// Lazy: the panel .vue is only loaded when the Settings view renders it.
const SettingAssistantConnection = defineAsyncComponent(() => import("../components/SettingAssistantConnection.vue"));

/**
 * Not a stored value: the Assistant tab's connection panel (the MCP
 * address, its status, and how to add it to an assistant). Lives in the
 * registry so it renders in its tab like every other setting.
 */
export class AssistantConnectionSetting extends BaseSetting<null> {
  constructor(category: string, label: string, key: string, options: SettingOptions = {}) {
    super(category, label, key, null, options);
  }

  get type(): string {
    return "assistant-connection";
  }

  get wide(): boolean {
    return true;
  }

  get component(): Component {
    return SettingAssistantConnection;
  }

  validate(): null {
    return null;
  }
}
