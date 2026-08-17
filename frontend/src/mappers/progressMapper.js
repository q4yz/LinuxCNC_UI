// Program-progress wire-shape mapper. Single source of truth for
// translating ``ProgramProgressResponse`` (Pydantic) into the
// ``ProgramProgress`` entity.

import { ProgramProgress, INTERP_STATES } from "../entities/progress/ProgramProgress.js";

/**
 * @param {object|null|undefined} wire
 * @returns {ProgramProgress}
 */
export function toProgramProgress(wire) {
  if (!wire || typeof wire !== "object") {
    return new ProgramProgress();
  }
  const interpStateRaw = Number(wire.interp_state);
  return new ProgramProgress({
    currentLine: Number(wire.current_line) || 0,
    motionLine: Number(wire.motion_line) || 0,
    totalLines: Number(wire.total_lines) || 0,
    file: typeof wire.file === "string" ? wire.file : "",
    interpState: Number.isFinite(interpStateRaw) ? interpStateRaw : INTERP_STATES.IDLE,
  });
}
