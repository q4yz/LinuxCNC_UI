// Pure helpers for the heater controls (no Vue): what the card shows
// for a `HeaterState` from the base-thread snapshot.

export interface HeaterLike {
  actualCelsius: number;
  targetCelsius: number;
  minTemp: number;
  maxTemp: number;
}

export type HeaterStatus = "off" | "heating" | "cooling" | "at-temp";

/** Within this many °C of the target counts as "at temperature". */
export const AT_TEMP_BAND_C = 2;

export function heaterStatus(h: HeaterLike | null | undefined): HeaterStatus {
  if (!h || h.targetCelsius <= 0) return "off";
  const diff = h.actualCelsius - h.targetCelsius;
  if (Math.abs(diff) <= AT_TEMP_BAND_C) return "at-temp";
  return diff < 0 ? "heating" : "cooling";
}

export function formatCelsius(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(1) : "—";
}

/** Bar fill 0..1: actual over the heater's range (max_temp). */
export function fillFraction(h: HeaterLike | null | undefined): number {
  if (!h || !(h.maxTemp > 0)) return 0;
  return Math.max(0, Math.min(1, h.actualCelsius / h.maxTemp));
}

/** Target marker position 0..1 on the same bar, or null when off. */
export function targetFraction(h: HeaterLike | null | undefined): number | null {
  if (!h || h.targetCelsius <= 0 || !(h.maxTemp > 0)) return null;
  return Math.max(0, Math.min(1, h.targetCelsius / h.maxTemp));
}

/** Clamp a typed set point into [minTemp, maxTemp]; 0 stays 0 (= off). */
export function clampTarget(value: number, h: HeaterLike | null | undefined): number {
  const v = Number(value);
  if (!Number.isFinite(v) || v <= 0) return 0;
  if (!h) return v;
  return Math.min(Math.max(v, h.minTemp), h.maxTemp);
}
