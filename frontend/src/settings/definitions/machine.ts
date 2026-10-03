// Machine-wide UI settings.
import { NumberSetting } from "../types/NumberSetting";
import { MacroButtonsSetting } from "../types/MacroButtonsSetting";

/**
 * Speed the jog slider starts at. The slider still caps it to the
 * fastest axis's own limit (``baseThread.maxAxisVelocity``).
 */
export const defaultJogVelocity = new NumberSetting(
  "Machine",
  "Default jog velocity",
  "machine.default_jog_velocity",
  500,
  { min: 1, step: 1, unit: "mm/s" },
  { description: "Starting speed of the jog slider; capped to the fastest axis limit." },
);

/**
 * One-click macro buttons next to the DRO axis rows and in the toolpath
 * viewer. One list for all slots: two lists sharing a store would
 * overwrite each other's rows on save.
 */
export const macroButtons = new MacroButtonsSetting(
  "Macro Buttons",
  "Custom buttons",
  "machine.macro_buttons",
  [
    { id: "dro.x", label: "DRO X axis row" },
    { id: "dro.y", label: "DRO Y axis row" },
    { id: "dro.z", label: "DRO Z axis row" },
    { id: "viewer.1", label: "Toolpath viewer — slot 1 (bottom-left)" },
    { id: "viewer.2", label: "Toolpath viewer — slot 2 (bottom-left)" },
    { id: "viewer.3", label: "Toolpath viewer — slot 3 (bottom-left)" },
  ],
  {
    description:
      "A button next to each DRO axis row or in the toolpath viewer's bottom-left corner runs a macro. Leave the macro empty to hide the button.",
  },
);
