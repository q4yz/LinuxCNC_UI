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
  return _commandResultFrom(
    ModulesMachineStateService.setMachineModeMachineState({ mode }),
    `set-mode:${mode}`,
  );
}

async function sendMdi(line: string): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesMachineStateService.machineMdi({ line }),
    "mdi",
  );
}

/**
 * Home a single axis (``axis >= 0``) or every axis (``axis === -1``,
 * the historical "home all" sentinel documented in
 * ``stores/machine.ts``).
 */
async function setHomeAxis(axis: number): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesAxisService.homeAxis({ axis }),
    axis === -1 ? "home:all" : `home:${axis}`,
  );
}

export const machineStateFacade = Object.freeze({
  setState,
  setMode,
  sendMdi,
  setHomeAxis,
});

export default machineStateFacade;
