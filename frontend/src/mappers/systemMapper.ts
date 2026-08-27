// System version mapper.

import type { VersionInfoResponse } from "../../generated/api/models/VersionInfoResponse";
import { SystemVersion } from "../entities/system";

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
    version: typeof w.version === "string" ? w.version : "",
    commit: typeof w.commit === "string" ? w.commit : "",
    isUpdatable: Boolean(w.update_available ?? w.isUpdatable),
    releaseNotes:
      typeof w.release_notes === "string" ? w.release_notes : null,
  });
}
