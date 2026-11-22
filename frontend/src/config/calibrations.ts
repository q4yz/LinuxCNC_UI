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
  skew: {
    title: "Skew",
    benefit: "Square parts: corrects X and Y not being exactly at 90° to each other.",
    steps: [
      "Start prints a square frame (heats, homes, then prints — a few minutes). Bed clear!",
      "Leave it on the bed or take it off; the solid tab marks corner A (front left).",
      "Measure the outer corners with calipers: diagonals AC and BD, the left side AD.",
      "Enter them below and save.",
    ],
    saves: "calibration.ini: the skew factor, active right away and at every start.",
  },
  pressure_advance: {
    title: "Pressure advance",
    benefit: "Sharp corners and even lines at speed: the extruder runs ahead of the pressure in the nozzle.",
    steps: [
      "Start prints a hollow tower; its pressure advance grows with the height (start + factor per mm).",
      "Look at the corners from the side: find the height where they are sharpest — no bulge, no gap.",
      "Measure that height from the bed (mm) and enter it below.",
      "Bowden: try factor 0.02; direct drive: 0.005.",
    ],
    saves: "calibration.ini: the pressure advance, active right away and at every start.",
  },
  extruder_steps: {
    title: "Extruder steps",
    benefit: "The extruder feeds exactly what is asked: the base for flow and pressure advance.",
    steps: [
      "Mark the filament 120 mm above the extruder's inlet (a pen, a ruler).",
      "Start heats, homes, lifts the nozzle and extrudes 100 mm slowly into the air.",
      "Measure from the inlet to the mark again (about 20 mm when right) and enter it.",
      "The new steps / mm apply from the next LinuxCNC start.",
    ],
    saves: "calibration.ini: [JOINT_n] SCALE of the extruder (at every start).",
  },
  flow: {
    title: "Flow",
    benefit: "Walls the width the slicer planned: no over-extrusion blobs, no gaps.",
    steps: [
      "Calibrate the extruder steps first.",
      "Start prints a single-wall cube (a brim on the bottom layer).",
      "Measure the wall with calipers at a few points above the brim, take the average.",
      "Enter it — the flow is set to match.",
    ],
    saves: "calibration.ini: the flow %, the print tuning's flow at every start.",
  },
  first_layer: {
    title: "First layer",
    benefit: "The right squish: lines that stick and touch, without scraping the nozzle.",
    steps: [
      "Start prints five patches, one layer: the middle one first.",
      "While it prints the middle patch, adjust the live Z offset with the buttons until the lines are flat and touch each other.",
      "Check the corner patches: big differences mean the bed mesh / Z tilt needs redoing.",
      "Once the print has finished, save: the live offset goes into the Z offset.",
    ],
    saves: "calibration.ini: the probe's z_offset (or Z's home position without a probe); from the next start.",
  },
  retraction: {
    title: "Retraction",
    benefit: "No strings between parts: just enough retraction, not more (that would grind the filament).",
    steps: [
      "Start prints two small towers; travelling between them retracts more with every millimetre of height.",
      "Find the height from which there are no more strings between the towers.",
      "Measure it from the bed and enter it.",
      "Used for G10 / G11: set the slicer to firmware retraction (and upload files again).",
    ],
    saves: "calibration.ini: [firmware_retraction] retract_length and speed, for files uploaded from then on.",
  },
  sensorless: {
    title: "Sensorless homing",
    benefit: "Homing without switches stops reliably at the end: no early stop, no grinding.",
    steps: [
      "Home the axis (Start). Keep a hand on the E-stop the first time.",
      "Tell how it went: stopped early (before the end), ground / did not stop at the end, or good.",
      "Save the suggested threshold and restart LinuxCNC — the driver gets it at the start — then home again.",
      "Repeat until good: each answer halves the range.",
    ],
    saves: "calibration.ini: the driver's StallGuard threshold, into the board config at every start.",
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
