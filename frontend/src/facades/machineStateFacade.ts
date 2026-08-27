// Machine-state facade. UI-facing API for machine-state reads +
// writes (set state, set mode, send MDI line, home axis).
//
// Reads piggyback on the existing ``stores/stateFacade.js`` (which
// owns the WebSocket transport). Writes go through the generated
// ``ModulesMachineStateService`` + ``ModulesAxisService`` and always
// return a ``CommandResult`` so the store / component layer can
// route through ``reportCommandFailure`` uniformly.

import {
  ModulesMachineStateService,
} from "../../generated/api/services/ModulesMachineStateService";
import { ModulesAxisService } from "../../generated/api/services/ModulesAxisService";
import { CommandResult } from "../entities/common/CommandResult";
import { describeError, errorStatus } from "../core/error-format";

async function _commandResultFrom(
  promise: Promise<unknown>,
  commandId: string,
): Promise<CommandResult> {
  try {
    await promise;
    return CommandResult.success({ commandId });
  } catch (err: unknown) {
    return CommandResult.failure(describeError(err), {
      commandId,
      statusCode: errorStatus(err),
    });
  }
}

async function setState(state: string): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineStateService.setMachineState({ state }),
    `set-state:${state}`,
  );
}

async function setMode(mode: 1 | 2 | 3 | 4): Promise<CommandResult> {
  // The generated client types ``_ModeCommand.mode`` as ``string``
  // (the backend accepts "manual" / "auto" / "mdi") while this
  // facade's historical contract accepted numeric literals. Cast
  // at the seam so the public API stays intact; nobody calls this
  // function today so the mismatch is dormant.
  return _commandResultFrom(
    ModulesMachineStateService.setMachineMode({ mode: mode as unknown as string }),
    `set-mode:${mode}`,
  );
}

async function sendMdi(line: string): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineStateService.runMdiCommand({ command: line }),
    "mdi",
  );
}

/**
 * Home a single axis by letter (``"x"|"y"|"z"``) or every axis when
 * ``axis === "all"``. The wire contract carries the canonical
 * LinuxCNC letter end-to-end so the backend can do the
 * ``letter → joint id(s)`` lookup without an index translation
 * layer.
 */
async function setHomeAxis(axis: "x" | "y" | "z" | "all"): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesAxisService.homeAxis({ axis }),
    axis === "all" ? "home:all" : `home:${axis}`,
  );
}

export const machineStateFacade = Object.freeze({
  setState,
  setMode,
  sendMdi,
  setHomeAxis,
});

export default machineStateFacade;
