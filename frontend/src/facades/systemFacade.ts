// System facade. Version read, update trigger + update progress.

import { SystemService } from "../../generated/api/services/SystemService";
import { CommandResult } from "../entities/common/CommandResult";
import { SystemVersion } from "../entities/system/SystemVersion";
import type { UpdateStatus } from "../entities/system/UpdateStatus";
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
 */
async function triggerUpdate(): Promise<CommandResult> {
  try {
    const wire = await SystemService.triggerSystemUpdate();
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

export const systemFacade = Object.freeze({
  fetchVersion,
  triggerUpdate,
  fetchUpdateStatus,
});

export default systemFacade;
