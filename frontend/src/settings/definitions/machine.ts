// Machine-wide UI settings.
import { CheckboxSetting } from "../types/CheckboxSetting";
import { MacroButtonsSetting } from "../types/MacroButtonsSetting";

/**
 * The system service starts LinuxCNC (the default machine) when the
 * device boots — always in E-stop. Read by the system service
 * (``services/MachineAutostart.py``); on unless switched off.
 */
export const machineAutostart = new CheckboxSetting(
  "Machine",
  "Start LinuxCNC with the device",
  "machine.autostart",
  true,
  {
    description:
      "When the device boots, LinuxCNC starts with the default machine, in E-stop: nothing moves " +
      "or heats until the E-stop is released.",
  },
);

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
      "A button next to each DRO axis row or in the bottom-left corner of the toolpath viewer / camera view runs a macro / NGC program — or, kind \"UI component\", opens a panel in a window you can drag and close; kind \"Output pin\" shows the output's own control (a toggle, a slider or a colour picker) next to the name. Leave the macro / component / output empty to hide the button.",
  },
);
