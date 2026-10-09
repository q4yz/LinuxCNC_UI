// System version mapper.

import type { UpdateStatusResponse } from "../../generated/api/models/UpdateStatusResponse";
import type { VersionInfoResponse } from "../../generated/api/models/VersionInfoResponse";
import { SystemVersion, UpdateStatus, type UpdateState } from "../entities/system";

const UPDATE_STATES: readonly UpdateState[] = ["idle", "running", "done", "failed"];

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
    // ``version`` is the commit hash; fall back to the release tag.
    version: w.version || w.current_version || "",
    latestVersion: w.latest_version || w.version || "",
    commit: typeof w.commit === "string" ? w.commit : "",
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
    phase: wire.phase ?? "",
    message: wire.message ?? "",
    startedAt: wire.started_at ?? null,
    finishedAt: wire.finished_at ?? null,
    commitBefore: wire.commit_before ?? null,
    commitAfter: wire.commit_after ?? null,
    logTail: wire.log_tail ?? "",
  });
}
