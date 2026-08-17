// Axis facade. Jog / home / keepalive commands. The runtime data
// (positions, status) still flows through ``stores/machine.js`` —
// this facade owns the write surface only.

import { ModulesAxisService } from "../../generated/api";
import { CommandResult } from "../entities";
import { describeError } from "../core/error-format";

async function _commandResultFrom(promise, commandId) {
  try {
    await promise;
    return CommandResult.success({ commandId });
  } catch (err) {
    return CommandResult.failure(describeError(err), {
      commandId,
      message: "Axis command failed",
    });
  }
}

async function jogStop() {
  return _commandResultFrom(ModulesAxisService.jogStop(), "jog-stop");
}

async function jogContinuous(payload) {
  return _commandResultFrom(
    ModulesAxisService.jogContinuous(payload),
    "jog-continuous",
  );
}

async function jogKeepalive() {
  return _commandResultFrom(ModulesAxisService.jogKeepalive(), "jog-keepalive");
}

async function home(axis) {
  return _commandResultFrom(ModulesAxisService.home({ axis }), `home:${axis}`);
}

export const axisFacade = Object.freeze({
  jogStop,
  jogContinuous,
  jogKeepalive,
  home,
});

export default axisFacade;
