// Temperature facade: setting a heater's target. The readings come with
// the base-thread snapshot (``stores/baseThread`` ``sensors``).

import { ModulesToolsService } from "../../generated/api/services/ModulesToolsService";
import { CommandResult } from "../entities/common/CommandResult";
import { describeError, errorStatus } from "../core/error-format";
import { HeaterControlRequest } from "../entities/tools/Heater";
import { toHeaterCommand } from "../mappers/toolsMapper";

/**
 * Set a heater's target temperature, through the tools module's
 * ``POST /tools/{tool_id}/target`` (the old
 * ``/temperature/sensors/{name}/target`` answers ``410 Gone``).
 */
async function setTarget(request: HeaterControlRequest): Promise<CommandResult> {
  try {
    const response = await ModulesToolsService.setToolTarget(request.toolId, toHeaterCommand(request));
    return CommandResult.success({ commandId: response.id ?? request.toolId, message: response.command ?? "" });
  } catch (err: unknown) {
    return CommandResult.failure(describeError(err), { commandId: request.toolId, statusCode: errorStatus(err) });
  }
}

export const temperatureFacade = Object.freeze({ setTarget });

export default temperatureFacade;
