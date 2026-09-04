import { Snapshot } from "../entities/baseThread/Snapshot";
import { toProgramProgress } from "./progressMapper";
import { toReadingSet } from "./temperatureMapper";
import { toToolList, type AnyToolWire } from "./toolsMapper";
import { AxisState } from "../entities/axis/AxisState";
import type { AxisStateResponse } from "../../generated/api/models/AxisStateResponse";


export function toAxisState(wire: unknown): AxisState {
  if (!wire || typeof wire !== "object") return new AxisState()
  const w = wire as Record<string, unknown>
  return new AxisState({
    id: typeof w.id === "string" ? w.id : "",
    jointNumbers: Array.isArray(w.joint_numbers) ? (w.joint_numbers as number[]) : [],
    minLimit: Number(w.min_limit) || 0,
    maxLimit: Number(w.max_limit) || 0,
  })
}

export function toAxesMap(wire: unknown): Record<string, AxisState> {
  if (!wire || typeof wire !== "object") return {}
  const out: Record<string, AxisState> = {}
  for (const [, raw] of Object.entries(wire as Record<string, unknown>)) {
    if (!raw || typeof raw !== "object") continue
    const axis = toAxisState(raw as AxisStateResponse)
    if (!axis.id) continue
    out[axis.id] = axis
  }
  return out
}


export function toSnapshot(wire: unknown): Snapshot {
  if (!wire || typeof wire !== "object") {
    return new Snapshot();
  }
  const w = wire as Record<string, unknown>

  return new Snapshot({
    progress: toProgramProgress(w.progress),
    readings: toReadingSet(w.sensors),
    toolList: toToolList(w.tools as Record<string, AnyToolWire> | AnyToolWire[] | null | undefined),
    axes: toAxesMap(w.axis),
    timestamp: typeof w.timestamp === "string" ? w.timestamp : null,
  });
}