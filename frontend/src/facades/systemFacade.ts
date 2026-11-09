// System facade. Version read, update trigger + update progress.

import { SystemService } from "../../generated/api/services/SystemService";
import type { ReleaseListResponse } from "../../generated/api/index";
import { CommandResult } from "../entities/common/CommandResult";
import { SystemVersion } from "../entities/system/SystemVersion";
import type { UpdateMode, UpdateStatus } from "../entities/system/UpdateStatus";
import { toSystemVersion, toUpdateStatus } from "../mappers/systemMapper";
import { describeError, errorStatus } from "../core/error-format";

/** Version info, or a failed ``CommandResult`` describing why it could not be read. */
async function fetchVersion(): Promise<SystemVersion | CommandResult> {
  try {
    const wire = await SystemService.getVersionInfo();
    return toSystemVersion(wire);
  } catch (err: unknown) {
    return CommandResult.failure(describeError(err), {
      commandId: "system-version",
      statusCode: errorStatus(err),
    });
  }
}

/**
 * Start the update. On success ``result.message`` is the run id to
 * follow with :func:`fetchUpdateStatus`; 409 while an update runs.
 *
 * ``commit`` builds the newest commit on the board (testing);
 * ``release`` installs a release with its prebuilt UI — ``tag`` picks
 * one (pre-releases and older ones too), none: the latest.
 */
async function triggerUpdate(mode: UpdateMode = "commit", tag?: string): Promise<CommandResult> {
  try {
    const wire = await SystemService.triggerSystemUpdate({ mode, tag: mode === "release" ? tag ?? null : null });
    return CommandResult.success({ commandId: "system-update", message: wire.run_id });
  } catch (err: unknown) {
    return CommandResult.failure(describeError(err), {
      commandId: "system-update",
      statusCode: errorStatus(err),
    });
  }
}

/**
 * Progress of the last update, or ``null`` when the system service
 * cannot be reached — expected while the update restarts it.
 */
async function fetchUpdateStatus(): Promise<UpdateStatus | null> {
  try {
    return toUpdateStatus(await SystemService.getSystemUpdateStatus());
  } catch {
    return null;
  }
}

/** Every GitHub release, newest first; ``null`` when it cannot be read. */
async function listReleases(): Promise<ReleaseListResponse | null> {
  try {
    return await SystemService.listReleases();
  } catch {
    return null;
  }
}

export type { ReleaseListResponse };

export const systemFacade = Object.freeze({
  fetchVersion,
  listReleases,
  triggerUpdate,
  fetchUpdateStatus,
});

export default systemFacade;
