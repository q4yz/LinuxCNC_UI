// MCU facade. Wraps the generated ``ModulesMcuService``.
//
// The MCU list itself is static config and arrives with the
// base-thread snapshot (``stores/baseThread.ts`` → ``mcus``); this
// facade only carries the actions. Every action returns a
// ``CommandResult`` so the store routes failures through
// ``reportCommandFailure`` like every other command.

import { ModulesMcuService } from "../../generated/api/services/ModulesMcuService";
import { CommandResult } from "../entities/common/CommandResult";
import { describeError, errorStatus } from "../core/error-format";

/**
 * Pulse the reset pin of every resettable MCU (Remora boards that
 * declared a ``reset_pin``). The backend answers 409 when there is
 * none; on success ``message`` lists the reset MCU ids.
 */
async function resetMcus(): Promise<CommandResult> {
  const commandId = "mcu:reset";
  try {
    const response = await ModulesMcuService.resetMcus();
    return CommandResult.success({ commandId, message: (response.reset ?? []).join(", ") });
  } catch (err: unknown) {
    return CommandResult.failure(describeError(err), {
      commandId,
      statusCode: errorStatus(err),
    });
  }
}

export const mcuFacade = Object.freeze({
  resetMcus,
});

export default mcuFacade;
