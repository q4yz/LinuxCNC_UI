// The Calibration tab's cards: per calibration kind (the backend's
// ``CalibrationItem.kind``) its title, what it is good for and how to run
// it. The backend says which the machine has, their results and reminders.

export interface CalibrationText {
  title: string;
  benefit: string;
  steps: string[];
  /** Where the result goes (shown under the result). */
  saves: string;
}

export const CALIBRATIONS: Record<string, CalibrationText> = {
  bed_mesh: {
    title: "Bed mesh",
    benefit: "Even first layers on a bed that is not flat: Z follows the measured surface.",
    steps: [
      "Heat the bed to printing temperature (it warps when hot).",
      "Home all axes, clean nozzle and bed.",
      "Start: the probe measures the grid; the mesh is saved and activated.",
    ],
    saves: "The mesh file (Details: view, edit, choose meshes).",
  },
  z_tilt: {
    title: "Z tilt",
    benefit: "A gantry parallel to the bed: the Z motors are levelled against each other.",
    steps: ["Home all axes.", "Start: probes the [z_tilt] points and corrects the Z motors until within tolerance."],
    saves: "The Z motor offsets (applied right away).",
  },
  probe_accuracy: {
    title: "Probe accuracy",
    benefit: "Shows whether the probe repeats — check it before trusting a mesh.",
    steps: ["Home, move the probe over the bed's middle.", "Start: probes the same spot several times."],
    saves: "Nothing — a range below ~0.01 mm is good.",
  },
  probe_z_offset: {
    title: "Probe Z offset",
    benefit: "The right nozzle height for the first layer: how far the nozzle is below the probe's trigger.",
    steps: [
      "Home all axes, clean the nozzle.",
      "Start: the probe touches the bed, the nozzle moves over that spot.",
      "Put a sheet of paper under the nozzle and lower it with the buttons until the paper just drags.",
      "Accept saves the offset.",
    ],
    saves: "calibration.ini: used for probing at once; for homing Z on the probe at the next start.",
  },
  pid: {
    title: "Heater PID",
    benefit: "Stable temperature: no overshoot when heating, no swinging while printing.",
    steps: [
      "Start cold, with the part fan as when printing.",
      "Start: the heater cycles around the target several times (minutes; longer for the bed).",
      "Stay near the printer. E-stop stops it.",
    ],
    saves: "calibration.ini: active right away, and at every start.",
  },
  input_shaper: {
    title: "Input shaper",
    benefit: "Less ringing / ghosting at high speed, so it can print faster.",
    steps: [
      "Mount the accelerometer firmly on the toolhead (or use the toolhead board's).",
      "Home X and Y, toolhead in the middle, nothing loose on the bed.",
      "Start: each axis is shaken from 5 to 133 Hz (about 2 minutes per axis, loud).",
    ],
    saves: "calibration.ini: the frequencies active right away, the shaper types too (and at every start).",
  },
};

/** Days to add for the reminder shortcuts. */
export const REMINDER_PRESETS: { label: string; days: number }[] = [
  { label: "1 week", days: 7 },
  { label: "1 month", days: 30 },
  { label: "3 months", days: 90 },
];

export function addDays(days: number, from: Date = new Date()): string {
  const d = new Date(from.getTime() + days * 86_400_000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** "3 days ago", "today", "never". */
export function relativeDate(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "never";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return iso;
  const day = (d: Date) => Math.floor((d.getTime() - d.getTimezoneOffset() * 60_000) / 86_400_000);
  const days = day(now) - day(then);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 60) return `${days} days ago`;
  return then.toLocaleDateString();
}
