// System facade. Version read + update trigger.

import { SystemService } from "../../generated/api/services/SystemService";
import { CommandResult } from "../entities/common/CommandResult";
import { SystemVersion } from "../entities/system/SystemVersion";
import { toSystemVersion } from "../mappers/systemMapper";
import { describeError, errorStatus } from "../core/error-format";

/**
 * @returns {Promise<SystemVersion>}
 */
async function fetchVersion() {
  try {
    const wire = await SystemService.getSystemVersion();
    return toSystemVersion(wire);
  } catch (err) {
    return new SystemVersion();
  }
}

async function triggerUpdate(): Promise<CommandResult> {
  try {
    await SystemService.postSystemUpdate();
    return CommandResult.success({ commandId: "system-update" });
  } catch (err: unknown) {
    return CommandResult.failure(describeError(err), {
      commandId: "system-update",
      statusCode: errorStatus(err),
    });
  }
}

export const systemFacade = Object.freeze({
  fetchVersion,
  triggerUpdate,
});

export default systemFacade;
