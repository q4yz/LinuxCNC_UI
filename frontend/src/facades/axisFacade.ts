// Axis facade. Jog / home / keepalive commands. The runtime data
// (positions, status) still flows through ``stores/machine.js`` —
// this facade owns the write surface only.

import { ModulesAxisService } from "../../generated/api/services/ModulesAxisService";
import { CommandResult } from "../entities";
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

async function jogStop(): Promise<CommandResult> {
  return _commandResultFrom(ModulesAxisService.jogStop(), "jog-stop");
}

async function jogContinuous(payload: unknown): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesAxisService.jogContinuous(payload as never),
    "jog-continuous",
  );
}

async function jogKeepalive(): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesAxisService.jogKeepalive(),
    "jog-keepalive",
  );
}

async function home(axis: number): Promise<CommandResult> {
  return _commandResultFrom(ModulesAxisService.home({ axis }), `home:${axis}`);
}

async function updateSettings(
  multiplier: number,
  absoluteSpeedLimit: number,
): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesAxisService.axisSettings({
      multiplier,
      absolute_speed_limit: absoluteSpeedLimit,
    }),
    "axis-settings",
  );
}

export const axisFacade = Object.freeze({
  jogStop,
  jogContinuous,
  jogKeepalive,
  home,
  updateSettings,
});

export default axisFacade;
