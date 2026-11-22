// Tools facade: spindle / extruder commands and heater targets
// (``/api/v1/modules/tools``). Every call resolves to a ``CommandResult``
// (failures included) so the store reports them uniformly. The tool list
// comes with the base-thread snapshot.

import { ModulesToolsService } from "../../generated/api/services/ModulesToolsService";
import type { ToolCommandResponse } from "../../generated/api/models/ToolCommandResponse";
import { CommandResult } from "../entities/common/CommandResult";
import { describeError, errorStatus } from "../core/error-format";
import { SpindleDigitalControlRequest } from "../entities/tools/SpindleDigital";
import { HeaterControlRequest } from "../entities/tools/Heater";
import { ExtruderControlRequest } from "../entities/tools/Extruder";
import { toSpindleCommand, toExtruderCommand, toHeaterCommand } from "../mappers/toolsMapper";

function fromToolCommand(response: ToolCommandResponse, fallbackId: string): CommandResult {
  return CommandResult.success({ commandId: response.tool_id ?? fallbackId, message: response.command ?? "" });
}

function failure(err: unknown, toolId: string): CommandResult {
  return CommandResult.failure(describeError(err), { commandId: toolId, statusCode: errorStatus(err) });
}

async function controlSpindle(request: SpindleDigitalControlRequest): Promise<CommandResult> {
  try {
    return fromToolCommand(await ModulesToolsService.controlSpindle(toSpindleCommand(request)), request.toolId);
  } catch (err: unknown) {
    return failure(err, request.toolId);
  }
}

async function controlExtruder(request: ExtruderControlRequest): Promise<CommandResult> {
  try {
    return fromToolCommand(await ModulesToolsService.controlExtruder(toExtruderCommand(request)), request.toolId);
  } catch (err: unknown) {
    return failure(err, request.toolId);
  }
}

/** A heater's target temperature. */
async function setTarget(request: HeaterControlRequest): Promise<CommandResult> {
  try {
    const response = await ModulesToolsService.setToolTarget(request.toolId, toHeaterCommand(request));
    return CommandResult.success({ commandId: response.id ?? request.toolId, message: response.command ?? "" });
  } catch (err: unknown) {
    return failure(err, request.toolId);
  }
}

export const toolsFacade = Object.freeze({ controlSpindle, controlExtruder, setTarget });

export default toolsFacade;
