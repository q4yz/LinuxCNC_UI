import { ModulesToolsService } from "../../generated/api/services/ModulesToolsService";
import { BaseThreadService } from "../../generated/api/services/BaseThreadService";
import { CommandResult } from "../entities/common/CommandResult";
import { ToolList } from "../entities/tools/ToolList";
import {
  toSpindleCommand,
  toExtruderCommand,
  toHeaterCommand,
  toToolList,
  type AnyToolWire,
} from "../mappers/toolsMapper";
import { describeError } from "../core/error-format";
import { SpindleDigitalControlRequest } from "../entities/tools/SpindleDigital";
import { HeaterControlRequest } from "../entities/tools/Heater";
import { ExtruderControlRequest } from "../entities/tools/Extruder";

export class ToolsService {
  // --- Reads -------------------------------------------------------------

  /**
   * Pure mapper — wraps `toToolList` so the facade owns the
   * wire-shape → entity translation. The base-thread polling loop
   * calls this on every tick; the mapper is idempotent and cheap.
   */
  static mapToolsWire(wires: AnyToolWire[] | Record<string, any>[] | null | undefined): ToolList {
    return toToolList(wires as AnyToolWire[]);
  }

  /**
   * Pull a fresh tool list straight from the snapshot endpoint.
   * Used by `toolStore.refreshToolsList` for post-deploy refreshes.
   */
  static async fetchTools(): Promise<ToolList> {
    const snapshot = await BaseThreadService.getBaseThreadSnapshot();
    return this.mapToolsWire(
      snapshot && Array.isArray(snapshot.tools) ? snapshot.tools : []
    );
  }

  // --- Writes ------------------------------------------------------------

  /**
   * Dispatch a spindle control command.
   */
  static async controlSpindle(request: SpindleDigitalControlRequest): Promise<CommandResult> {
    const cmd = toSpindleCommand(request);
    try {
      const response = await ModulesToolsService.controlSpindle(cmd);
      return CommandResult.success({
        commandId: response && (response as any).tool_id ? (response as any).tool_id : request.toolId,
        message: response && (response as any).command ? (response as any).command : "ok",
      });
    } catch (err: unknown) {
      return CommandResult.failure(describeError(err), {
        commandId: request.toolId,
        message: "Spindle command failed",
      });
    }
  }

  /**
   * Dispatch an extruder control command.
   */
  static async controlExtruder(request: ExtruderControlRequest): Promise<CommandResult> {
    const cmd = toExtruderCommand(request);
    try {
      const response = await ModulesToolsService.controlExtruder(cmd);
      return CommandResult.success({
        commandId: response && (response as any).tool_id ? (response as any).tool_id : request.toolId,
        message: response && (response as any).command ? (response as any).command : "ok",
      });
    } catch (err: unknown) {
      return CommandResult.failure(describeError(err), {
        commandId: request.toolId,
        message: "Extruder command failed",
      });
    }
  }

  /**
   * Set a heater's target temperature.
   */
  static async setTarget(request: HeaterControlRequest): Promise<CommandResult> {
    const cmd = toHeaterCommand(request);
    try {
      const response = await ModulesToolsService.setToolTarget({
        toolId: request.toolId,
        requestBody: cmd,
      });
      return CommandResult.success({
        commandId: response && (response as any).tool_id ? (response as any).tool_id : request.toolId,
        message: response && (response as any).command ? (response as any).command : "ok",
      });
    } catch (err: unknown) {
      return CommandResult.failure(describeError(err), {
        commandId: request.toolId,
        message: "Tool target failed",
      });
    }
  }
}