// What a macro button of kind "output" can drive, from the machine's live
// state (``stores/baseThread``: ``io`` and ``leds``) — the stored target is
// ``"<type>:<id>"`` in the descriptor's ``macroName``:
//
//   out:<id>  [output_pin] switched -> a toggle;  PWM -> a slider 0 … scale
//   fan:<id>  [fan]                 -> a slider 0 … 100 %
//   led:<id>  [neopixel] chain      -> a colour picker (the whole chain)
import type { IoState, Led } from "../../generated/api";

export type OutputControlKind = "toggle" | "slider" | "color";

export interface OutputTarget {
  value: string;
  label: string;
  control: OutputControlKind;
  /** Slider: its full value (a PWM pin's scale, 100 for a fan). */
  max: number;
  unit: string;
}

const pretty = (id: string) => id.replace(/_/g, " ");

export function outputTargets(io: IoState | null | undefined, leds: Led[] | null | undefined): OutputTarget[] {
  const out: OutputTarget[] = [];
  for (const o of io?.outputs ?? []) {
    out.push(o.pwm
      ? { value: `out:${o.id}`, label: `${pretty(o.id)} (PWM)`, control: "slider", max: o.scale ?? 1, unit: "" }
      : { value: `out:${o.id}`, label: `${pretty(o.id)} (on / off)`, control: "toggle", max: 1, unit: "" });
  }
  for (const f of io?.fans ?? []) {
    out.push({ value: `fan:${f.id}`, label: `${pretty(f.id)} (fan)`, control: "slider", max: 100, unit: "%" });
  }
  for (const led of leds ?? []) {
    out.push({ value: `led:${led.id}`, label: `${pretty(led.id)} (RGB)`, control: "color", max: 1, unit: "" });
  }
  return out;
}

/** The target ``value`` names, or ``undefined`` when the machine has no such output (now). */
export function findTarget(value: string, io: IoState | null | undefined, leds: Led[] | null | undefined): OutputTarget | undefined {
  return outputTargets(io, leds).find((t) => t.value === value);
}

/** ``"out:light"`` -> ``["out", "light"]``. */
export function splitTarget(value: string): [string, string] {
  const at = value.indexOf(":");
  return at < 0 ? ["", value] : [value.slice(0, at), value.slice(at + 1)];
}
