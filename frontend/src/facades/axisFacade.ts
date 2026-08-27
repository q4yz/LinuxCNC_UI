// Axis facade. Home + axis-settings commands. Runtime data
// (positions, status) still flows through ``stores/machine.js`` —
// this facade owns the write surface only.
//
// Jog / keepalive commands were previously exposed here but the
// runtime jog pipeline moved to the WebSocket layer
// (``facades/servoThreadFacade.ts``). The HTTP ``/axis/jog*`` endpoints
// were retired; the regenerated client no longer exposes them, so
// the dead HTTP jog methods are removed. Call ``machineStore.jogContinuous``
// and ``machineStore.jogStop`` for the live jog pipeline.

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

async function home(axis: "x" | "y" | "z" | "all"): Promise<CommandResult> {
  return _commandResultFrom(
    ModulesAxisService.homeAxis({ axis }),
    `home:${axis}`,
  );
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
  home,
  updateSettings,
});

export default axisFacade;
