import { Snapshot } from "../entities/base/Snapshot";
import { toProgramProgress } from "./progressMapper";
import { toReadingSet } from "./temperatureMapper";
import { toToolList } from "./toolsMapper";


export function toSnapshot(wire: any): Snapshot {
  if (!wire || typeof wire !== "object") {
    return new Snapshot();
  }

  return new Snapshot({
    progress: toProgramProgress(wire.progress),
    readings: toReadingSet(wire.sensors),
    toolList: toToolList(wire.tools),
    timestamp: typeof wire.timestamp === "string" ? wire.timestamp : null,
  });
}