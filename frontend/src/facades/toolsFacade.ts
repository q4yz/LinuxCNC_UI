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
import { describeError, errorStatus } from "../core/error-format";
import { SpindleDigitalControlRequest } from "../entities/tools/SpindleDigital";
import { HeaterControlRequest } from "../entities/tools/Heater";
import { ExtruderControlRequest } from "../entities/tools/Extruder";
import type { ToolCommandResponse } from "../../generated/api/models/ToolCommandResponse";
import type { HeaterCommandStateResponse } from "../../generated/api/models/HeaterCommandStateResponse";

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
      return ToolsService.fromToolCommandResponse(response, request.toolId);
    } catch (err: unknown) {
      return CommandResult.failure(describeError(err), {
        commandId: request.toolId,
        statusCode: errorStatus(err),
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
      return ToolsService.fromToolCommandResponse(response, request.toolId);
    } catch (err: unknown) {
      return CommandResult.failure(describeError(err), {
        commandId: request.toolId,
        statusCode: errorStatus(err),
      });
    }
  }

  /**
   * Set a heater's target temperature.
   */
  static async setTarget(request: HeaterControlRequest): Promise<CommandResult> {
    const cmd = toHeaterCommand(request);
    try {
      const response = await ModulesToolsService.setToolTarget(request.toolId, cmd);
      return ToolsService.fromHeaterCommandResponse(response, request.toolId);
    } catch (err: unknown) {
      return CommandResult.failure(describeError(err), {
        commandId: request.toolId,
        statusCode: errorStatus(err),
      });
    }
  }

  /**
   * Success-path constructor for spindle / extruder commands.
   * Centralises the wire-field → ``CommandResult`` translation so
   * every call site uses the same defensive defaults and the typed
   * generated response shape (no more ``(response as any)`` casts).
   */
  private static fromToolCommandResponse(
    response: ToolCommandResponse,
    fallbackCommandId: string,
  ): CommandResult {
    return CommandResult.success({
      commandId: response.tool_id ?? fallbackCommandId,
      message: response.command ?? "",
    });
  }

  /**
   * Success-path constructor for heater target commands.
   */
  private static fromHeaterCommandResponse(
    response: HeaterCommandStateResponse,
    fallbackCommandId: string,
  ): CommandResult {
    return CommandResult.success({
      commandId: response.id ?? fallbackCommandId,
      message: response.command ?? "",
    });
  }
}

/**
 * Legacy positional-API wrapper.
 *
 * `toolStore.ts` (and other pre-OOP call sites) still calls the
 * facade with positional arguments. `ToolsService` takes request
 * objects now, so this wrapper adapts the old call sites to the
 * new static API without duplicating dispatch logic.
 */
export const toolsFacade = {
  async controlSpindle(
    toolId: string,
    action: string,
    speed: number,
    masterOverride: number = 0,
    masterOverrideEnable: boolean = false,
    override: number = 1.0,
  ): Promise<CommandResult> {
    return ToolsService.controlSpindle(
      new SpindleDigitalControlRequest({
        toolId,
        action,
        speed,
        masterOverride,
        masterOverrideEnable,
        override,
      }),
    );
  },

  async controlExtruder(
    toolId: string,
    action: string,
    distance: number,
    speed: number,
    heaterTarget?: number,
    heaterAction: string = "noop",
  ): Promise<CommandResult> {
    return ToolsService.controlExtruder(
      new ExtruderControlRequest({
        toolId,
        action,
        distance,
        speed,
        heater:
          heaterTarget !== undefined
            ? { id: toolId, target: heaterTarget }
            : null,
        heaterAction,
      }),
    );
  },

  async setTarget(toolId: string, target: number): Promise<CommandResult> {
    return ToolsService.setTarget(new HeaterControlRequest({ toolId, target }));
  },
};
