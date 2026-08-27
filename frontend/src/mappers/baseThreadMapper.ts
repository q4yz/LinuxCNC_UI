import { Snapshot } from "../entities/baseThread/Snapshot";
import { toProgramProgress } from "./progressMapper";
import { toReadingSet } from "./temperatureMapper";
import { toToolList } from "./toolsMapper";
import { AxisState } from "../entities/axis/AxisState";
import type { AxisStateResponse } from "../../generated/api/models/AxisStateResponse";


export function toAxisState(wire: any): AxisState {
  if (!wire || typeof wire !== "object") return new AxisState()
  return new AxisState({
    id: typeof wire.id === "string" ? wire.id : "",
    jointNumbers: Array.isArray(wire.joint_numbers) ? wire.joint_numbers : [],
    minLimit: Number(wire.min_limit) || 0,
    maxLimit: Number(wire.max_limit) || 0,
  })
}

export function toAxesMap(wire: any): Record<string, AxisState> {
  if (!wire || typeof wire !== "object") return {}
  const out: Record<string, AxisState> = {}
  for (const [letter, raw] of Object.entries(wire)) {
    if (!raw || typeof raw !== "object") continue
    const axis = toAxisState(raw as AxisStateResponse)
    if (!axis.id) continue
    out[axis.id] = axis
  }
  return out
}


export function toSnapshot(wire: any): Snapshot {
  if (!wire || typeof wire !== "object") {
    return new Snapshot();
  }

  return new Snapshot({
    progress: toProgramProgress(wire.progress),
    readings: toReadingSet(wire.sensors),
    toolList: toToolList(wire.tools),
    axes: toAxesMap(wire.axis),
    timestamp: typeof wire.timestamp === "string" ? wire.timestamp : null,
  });
}