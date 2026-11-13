// Machine-wide UI settings.
import { MacroButtonsSetting } from "../types/MacroButtonsSetting";

/**
 * One-click macro buttons next to the DRO axis rows, in the toolpath
 * viewer and in the camera view. One list for all slots: two lists sharing a store would
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
    { id: "camera.1", label: "Camera view — slot 1 (bottom-left)" },
    { id: "camera.2", label: "Camera view — slot 2 (bottom-left)" },
    { id: "camera.3", label: "Camera view — slot 3 (bottom-left)" },
  ],
  {
    description:
      "A button next to each DRO axis row or in the bottom-left corner of the toolpath viewer / camera view runs a macro. Leave the macro empty to hide the button.",
  },
);
