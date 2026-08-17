// System version mapper.

import { SystemVersion } from "../entities/system/SystemVersion";

/**
 * @param {object|null|undefined} wire
 * @returns {SystemVersion}
 */
export function toSystemVersion(wire) {
  if (!wire || typeof wire !== "object") {
    return new SystemVersion();
  }
  return new SystemVersion({
    version: typeof wire.version === "string" ? wire.version : "",
    commit: typeof wire.commit === "string" ? wire.commit : "",
    isUpdatable: Boolean(wire.is_updatable ?? wire.isUpdatable),
    releaseNotes:
      typeof wire.release_notes === "string" ? wire.release_notes : null,
  });
}
