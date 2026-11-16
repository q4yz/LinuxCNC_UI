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
    description:
      "\"Upload and print\" in OrcaSlicer / PrusaSlicer / Cura starts the print like the Start button " +
      "(homing and levelling of the file first). The machine must be on and nothing else running. " +
      "Off: the file is only loaded.",
  },
);
