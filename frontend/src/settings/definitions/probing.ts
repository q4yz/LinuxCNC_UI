// Probing cycles (the Dashboard's Probing panel): the probe's tip and the
// search feed every cycle passes to its macro (macros/probe_*.ngc).
import { NumberSetting } from "../types/NumberSetting";

export const probeDiameter = new NumberSetting(
  "Probing",
  "Probe tip diameter",
  "probing.probe_diameter",
  4.0,
  { min: 0, max: 50, step: 0.01, unit: "mm" },
  { description: "The touch probe's ball diameter: the cycles correct every touch by its radius.", order: 0 },
);

export const probingFeedrate = new NumberSetting(
  "Probing",
  "Search feed",
  "probing.feedrate",
  100.0,
  { min: 1, max: 5000, step: 1, unit: "mm/min" },
  { description: "How fast the probe moves towards the part while searching.", order: 1 },
);
