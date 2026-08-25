import { BaseThreadService } from "../../generated/api/services/BaseThreadService";
import { ModulesToolsService } from "../../generated/api/services/ModulesToolsService";
import { CommandResult } from "../entities/common/CommandResult";
import { ReadingSet } from "../entities/temperature/ReadingSet";
import { toReadingSet } from "../mappers/temperatureMapper";
import { describeError, errorStatus } from "../core/error-format";

// Adjust the import path based on where you saved the class
import { HeaterControlRequest } from "../entities/tools/Heater";
import { toHeaterCommand } from "../mappers/toolsMapper";
import type { HeaterCommandStateResponse } from "../../generated/api/models/HeaterCommandStateResponse";

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
            const cmd = toHeaterCommand(request);

            const response = await ModulesToolsService.setToolTarget(request.toolId, cmd);

            return TemperatureService.fromHeaterCommandResponse(response, request.toolId);
        } catch (err: unknown) {
            return CommandResult.failure(describeError(err), {
                commandId: request.toolId,
                statusCode: errorStatus(err),
            });
        }
    }

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

export default TemperatureService;

/**
 * Legacy positional-API wrapper.
 *
 * `modules/temperature/store.ts` (and other pre-OOP call sites)
 * still calls the facade with positional arguments. `TemperatureService`
 * takes a `HeaterControlRequest` object now, so this wrapper adapts the
 * old call sites to the new static API without duplicating dispatch logic.
 */
export const temperatureFacade = {
    async setTarget(toolId: string, target: number): Promise<CommandResult> {
        return TemperatureService.setTarget(
            new HeaterControlRequest({toolId, target}),
        );
    },

    async fetchReadings(): Promise<ReadingSet> {
        return TemperatureService.fetchReadings();
    },
};
