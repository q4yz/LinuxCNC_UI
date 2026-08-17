import { BaseThreadService } from "../../generated/api/services/BaseThreadService";
import { ModulesToolsService } from "../../generated/api/services/ModulesToolsService";
import { CommandResult } from "../entities/common/CommandResult";
import { ReadingSet } from "../entities/temperature/ReadingSet";
import { toReadingSet, toHeaterSetTargetRequest } from "../mappers/temperatureMapper";
import { describeError } from "../core/error-format";

// Adjust the import path based on where you saved the class
import type { HeaterControlRequest } from "../entities/temperature/HeaterControlRequest";

export class TemperatureService {
  /**
   * Fetch the current temperature readings from the base-thread
   * snapshot. Returns an empty `ReadingSet` if the snapshot is
   * missing or malformed.
   */
  static async fetchReadings(): Promise<ReadingSet> {
    try {
      const snapshot = await BaseThreadService.getBaseThreadSnapshot();
      return toReadingSet(snapshot?.sensors);
    } catch (err: unknown) {
      console.error("[TemperatureService] Failed to fetch readings", err);
      // Return an empty ReadingSet on HTTP failure to prevent the UI from crashing
      return new ReadingSet([]);
    }
  }

  /**
   * Set the target temperature for a heater. Routes through the
   * `tools` module's `POST /tools/{tool_id}/target` endpoint —
   * the historical `/temperature/sensors/{name}/target` endpoint
   * is deprecated and returns `410 Gone`.
   */
  static async setTarget(request: HeaterControlRequest): Promise<CommandResult> {
    try {
      const requestBody = toHeaterSetTargetRequest(request.toolId, request.target);

      const response = await ModulesToolsService.setToolTarget({
        toolId: request.toolId,
        requestBody,
      });

      return CommandResult.success({
        commandId: response && (response as any).command_id ? (response as any).command_id : (response as any).tool_id ?? request.toolId,
        message: response && (response as any).command ? (response as any).command : "ok",
      });
    } catch (err: unknown) {
      return CommandResult.failure(describeError(err), {
        commandId: request.toolId,
        message: "Failed to set target",
      });
    }
  }
}

export default TemperatureService;