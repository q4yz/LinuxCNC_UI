// System version mapper.

import type { UpdateStatusResponse } from "../../generated/api/models/UpdateStatusResponse";
import type { VersionInfoResponse } from "../../generated/api/models/VersionInfoResponse";
import { SystemVersion, UpdateStatus, type UpdateMode, type UpdateState } from "../entities/system";

const UPDATE_STATES: readonly UpdateState[] = ["idle", "running", "done", "failed"];
const UPDATE_MODES: readonly UpdateMode[] = ["commit", "release"];

export function toSystemVersion(wire: unknown): SystemVersion {
  if (!wire || typeof wire !== "object") {
    return new SystemVersion();
  }
  const w = wire as VersionInfoResponse & {
    commit?: unknown;
    release_notes?: unknown;
    isUpdatable?: unknown;
  };
  return new SystemVersion({
    // ``current_version`` is git describe (release tag on a release
    // install); ``version`` the short commit hash.
    version: w.current_version || w.version || "",
    latestVersion: w.latest_version || "",
    commit: typeof w.commit === "string" ? w.commit : w.version || "",
    isUpdatable: Boolean(w.update_available ?? w.isUpdatable),
    releaseNotes:
      typeof w.release_notes === "string" ? w.release_notes : null,
  });
}

export function toUpdateStatus(wire: UpdateStatusResponse | null | undefined): UpdateStatus {
  if (!wire || typeof wire !== "object") return new UpdateStatus();
  return new UpdateStatus({
    runId: wire.run_id ?? null,
    state: UPDATE_STATES.includes(wire.state) ? wire.state : "idle",
    mode: wire.mode && UPDATE_MODES.includes(wire.mode) ? wire.mode : null,
    phase: wire.phase ?? "",
    message: wire.message ?? "",
    startedAt: wire.started_at ?? null,
    finishedAt: wire.finished_at ?? null,
    commitBefore: wire.commit_before ?? null,
    commitAfter: wire.commit_after ?? null,
    logTail: wire.log_tail ?? "",
  });
}
