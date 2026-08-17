import { ProgramProgress, InterpState } from "../entities/progress/ProgramProgress";
import type { ProgramProgressResponse } from "../../generated/api";

/**
 * Maps the backend's wire shape to the ProgramProgress entity.
 *
 * @param wire The raw snapshot entry from the backend.
 * @returns A strongly typed ProgramProgress instance.
 */
export function toProgramProgress(wire: ProgramProgressResponse | Record<string, any> | null | undefined): ProgramProgress {
  if (!wire || typeof wire !== "object") {
    return new ProgramProgress();
  }

  const interpStateRaw = Number(wire.interp_state);

  return new ProgramProgress({
    currentLine: Number(wire.current_line) || 0,
    motionLine: Number(wire.motion_line) || 0,
    totalLines: Number(wire.total_lines) || 0,
    file: typeof wire.file === "string" ? wire.file : "",
    interpState: Number.isFinite(interpStateRaw) ? interpStateRaw : InterpState.IDLE,
  });
}