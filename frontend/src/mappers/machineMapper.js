// Machine state mapper. ``stores/stateFacade.js`` already wraps the
// runtime state in a MachineState-like object; this mapper is for
// consumers that build synthetic states (tests, dev tooling) from
// the raw servo-thread payload.

import { MachineState } from "../entities/machine/MachineState.js";

/**
 * @param {object|null|undefined} payload
 * @returns {MachineState}
 */
export function toMachineState(payload) {
  if (!payload || typeof payload !== "object") {
    return new MachineState();
  }
  // Map the servo-thread ``task_state`` int to the string enum.
  const taskStateMap = {
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
    typeof payload.state === "string"
      ? payload.state
      : taskStateMap[Number(payload.task_state)] || "off";
  return new MachineState({
    state,
    mode: typeof payload.mode === "string" ? payload.mode : "manual",
    isOnline: typeof payload.isOnline === "boolean" ? payload.isOnline : Boolean(payload.connected),
    isEstopped: Boolean(payload.estop || payload.isEstopped),
    lastError: typeof payload.lastError === "string" ? payload.lastError : null,
  });
}
