// Pure conversion between the persisted camera-preference map (wire
// shape, snake_case — the ``camera.preferences`` UI setting) and the
// camelCase ``CameraPreference`` rows the camera store and components
// use. No store/settings imports, so both the store and the setting
// type can use it without an import cycle.

import type { CameraPreference, CameraPreferenceMap, WirePreferenceMap } from "./cameraTypes";

/** Canonical quarter-turn angles; anything else coerces to 0. */
export const ROTATE_VALUES: ReadonlySet<number> = new Set([0, 90, 180, 270]);

export function defaultPreference(): CameraPreference {
  return { customName: "", rotate: 0, mirror: false, hidden: false };
}

export function coerceRotate(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return 0;
  return ROTATE_VALUES.has(value) ? value : 0;
}

/**
 * One stored row → ``CameraPreference``. Tolerant of malformed input
 * (null, primitives, arrays) so a stale or hand-edited settings file
 * never crashes the camera panel. Reads the persisted snake_case
 * ``custom_name``.
 */
export function coercePreference(value: unknown): CameraPreference {
  if (!value || typeof value !== "object" || Array.isArray(value)) return defaultPreference();
  const row = value as Partial<Record<keyof CameraPreference | "custom_name", unknown>>;
  return {
    customName: typeof row.custom_name === "string" ? row.custom_name : "",
    rotate: coerceRotate(row.rotate),
    mirror: row.mirror === true,
    hidden: row.hidden === true,
  };
}

export function serializePreferences(prefs: CameraPreferenceMap | null | undefined): WirePreferenceMap {
  const out: WirePreferenceMap = {};
  if (!prefs || typeof prefs !== "object") return out;
  for (const [id, pref] of Object.entries(prefs)) {
    if (!id || !pref || typeof pref !== "object") continue;
    const row = pref as Partial<CameraPreference>;
    out[id] = {
      custom_name: typeof row.customName === "string" ? row.customName : "",
      rotate: coerceRotate(row.rotate),
      mirror: row.mirror === true,
      hidden: row.hidden === true,
    };
  }
  return out;
}

export function deserializePreferences(value: unknown): CameraPreferenceMap {
  const out: CameraPreferenceMap = {};
  if (!value || typeof value !== "object" || Array.isArray(value)) return out;
  for (const [id, raw] of Object.entries(value as Record<string, unknown>)) {
    if (!id || typeof id !== "string") continue;
    out[id] = coercePreference(raw);
  }
  return out;
}
