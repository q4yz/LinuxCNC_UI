// Machine state mapper. ``stores/stateFacade.js`` already wraps the
// runtime state in a MachineState-like object; this mapper is for
// consumers that build synthetic states (tests, dev tooling) from
// the raw servo-thread payload.

import { MachineState } from "../entities/machine/MachineState";

export function toMachineState(payload: unknown): MachineState {
  if (!payload || typeof payload !== "object") {
    return new MachineState();
  }
  const p = payload as Record<string, unknown>;
  // Map the servo-thread ``task_state`` int to the string enum.
  const taskStateMap: Record<number, string> = {
    1: "idle",
    2: "loaded",
    3: "running",
    4: "paused",
    5: "fault",
    6: "estop",
    7: "off",
    8: "updating",
  };
  const state =
    typeof p.state === "string"
      ? p.state
      : taskStateMap[Number(p.task_state)] || "off";
  return new MachineState({
    state,
    mode: typeof p.mode === "string" ? p.mode : "manual",
    isOnline:
      typeof p.isOnline === "boolean"
        ? p.isOnline
        : Boolean(p.connected),
    isEstopped: Boolean(p.estop || p.isEstopped),
    lastError: typeof p.lastError === "string" ? p.lastError : null,
  });
}
