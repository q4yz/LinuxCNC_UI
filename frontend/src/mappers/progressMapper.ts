import { ProgramProgress, InterpState } from "../entities/progress/ProgramProgress";

/**
 * Maps the backend's wire shape to the ProgramProgress entity.
 *
 * @param wire The raw snapshot entry from the backend.
 * @returns A strongly typed ProgramProgress instance.
 */
export function toProgramProgress(wire: unknown): ProgramProgress {
  if (!wire || typeof wire !== "object") {
    return new ProgramProgress();
  }
  const w = wire as Record<string, unknown>;
  const interpStateRaw = Number(w.interp_state);

  return new ProgramProgress({
    currentLine: Number(w.current_line) || 0,
    motionLine: Number(w.motion_line) || 0,
    totalLines: Number(w.total_lines) || 0,
    file: typeof w.file === "string" ? w.file : "",
    interpState: Number.isFinite(interpStateRaw) ? interpStateRaw : InterpState.IDLE,
  });
}