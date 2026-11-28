// Slicer uploads (the OctoPrint-compatible API of the system service).
import { CheckboxSetting } from "../types/CheckboxSetting";

/**
 * The slicer's "Upload and print" starts the file (read by the system
 * service's SlicerUploadService). Off: it is only loaded and started at
 * the machine.
 */
export const slicerAllowStart = new CheckboxSetting(
  "Slicer",
  "Start prints sent from the slicer",
  "slicer.allow_start",
  false,
  {
    order: 0,
    description:
      "\"Upload and print\" in OrcaSlicer / PrusaSlicer / Cura starts the print like the Start button " +
      "(homing and levelling of the file first). The machine must be on and nothing else running. " +
      "Off: the file is only loaded.",
  },
);

/**
 * With "Start prints" on: the job releases the E-stop and switches the
 * machine on itself, and switches it off once the job ended (finished,
 * stopped or failed). Read by the system service's SlicerUploadService.
 */
export const slicerPowerCycle = new CheckboxSetting(
  "Slicer",
  "Power on for the job, off when done",
  "slicer.power_cycle",
  false,
  {
    order: 1,
    description:
      "Needs \"Start prints sent from the slicer\". The print releases the E-stop and switches the " +
      "machine on, then switches it off when the G-code ended (also when it is stopped or fails). " +
      "An E-stop pressed during the print stays an E-stop.",
  },
);
