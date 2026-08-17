// Machine-state facade. UI-facing API for machine-state reads +
// writes (set state, set mode, send MDI line, home axis).
//
// Reads piggyback on the existing ``stores/stateFacade.js`` (which
// owns the WebSocket transport). Writes go through the generated
// ``ModulesMachineStateService`` + ``ModulesAxisService``.

import {
  ModulesMachineStateService,
} from "../../generated/api/services/ModulesMachineStateService";
import { ModulesAxisService } from "../../generated/api/services/ModulesAxisService";
import { CommandResult } from "../entities/common/CommandResult";
import { describeError } from "../core/error-format";

async function _commandResultFrom(promise, commandId) {
  try {
    await promise;
    return CommandResult.success({ commandId });
  } catch (err) {
    return CommandResult.failure(describeError(err), {
      commandId,
      message: "Command failed",
    });
  }
}

async function setState(state) {
  return _commandResultFrom(
    ModulesMachineStateService.setStateMachineState({ state }),
    `set-state:${state}`,
  );
}

async function setMode(mode) {
  return _commandResultFrom(
    ModulesMachineStateService.setMachineModeMachineState({ mode }),
    `set-mode:${mode}`,
  );
}

async function sendMdi(line) {
  return _commandResultFrom(
    ModulesMachineStateService.machineMdi({ line }),
    "mdi",
  );
}

async function homeAxis(axis) {
  return _commandResultFrom(ModulesAxisService.home({ axis }), `home:${axis}`);
}

export const machineStateFacade = Object.freeze({
  setState,
  setMode,
  sendMdi,
  homeAxis,
});

export default machineStateFacade;
