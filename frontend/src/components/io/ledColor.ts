// LED colour helpers (no imports, so the node tests load them directly):
// ``<input type="color">``'s ``#rrggbb`` <-> Klipper SET_LED channels 0 ... 1.

export interface LedColor {
  red: number;
  green: number;
  blue: number;
}

/** ``#rrggbb`` -> 0 ... 1 channels. */
export function hexToColor(hex: string): LedColor {
  const value = Number.parseInt(hex.replace("#", ""), 16) || 0;
  return { red: ((value >> 16) & 255) / 255, green: ((value >> 8) & 255) / 255, blue: (value & 255) / 255 };
}

/** 0 ... 1 channels -> ``#rrggbb``. */
export function colorToHex(color: LedColor): string {
  const byte = (v: number) => Math.max(0, Math.min(255, Math.round(v * 255))).toString(16).padStart(2, "0");
  return `#${byte(color.red)}${byte(color.green)}${byte(color.blue)}`;
}
