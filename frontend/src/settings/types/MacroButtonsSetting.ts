import { defineAsyncComponent, type Component } from "vue";
import { BaseSetting, type SettingOptions } from "../core/BaseSetting";
import {
  normaliseMacroButtons,
  type MacroButtonDescriptor,
  type MacroButtonSlotDef,
} from "../../ui/macroButtonTypes";

// Lazy: the editor .vue is only loaded when the Settings view renders it.
const SettingMacroButtons = defineAsyncComponent(() => import("../components/SettingMacroButtons.vue"));

/**
 * Configurable macro buttons for a set of panel slots. The slot list is
 * part of the definition (config), so the editor shows one row per slot.
 */
export class MacroButtonsSetting extends BaseSetting<MacroButtonDescriptor[]> {
  constructor(
    category: string,
    label: string,
    key: string,
    slots: MacroButtonSlotDef[],
    options: SettingOptions = {},
  ) {
    super(category, label, key, [], { ...options, config: { slots } });
  }

  get type(): string {
    return "macro-buttons";
  }

  get component(): Component {
    return SettingMacroButtons;
  }

  get slots(): MacroButtonSlotDef[] {
    return (this.config.slots as MacroButtonSlotDef[]) ?? [];
  }

  /** Slot id → descriptor, for hosts rendering ``MacroButton``. Reactive. */
  get bySlot(): Record<string, MacroButtonDescriptor | undefined> {
    const map: Record<string, MacroButtonDescriptor> = {};
    for (const row of this.value ?? []) map[row.slot] = row;
    return map;
  }

  validate(raw: unknown): MacroButtonDescriptor[] | undefined {
    return Array.isArray(raw) ? normaliseMacroButtons(raw) : undefined;
  }
}
