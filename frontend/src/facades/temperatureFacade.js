// Temperature facade. The single UI-facing API for temperature
// reads + writes. Components and stores call this; nobody else
// imports the generated OpenAPI client directly for temperature
// operations.
//
// Reads come through the shared base-thread snapshot (one HTTP
// request per second covers every slow stream). Writes go to the
// ``tools`` module's heater endpoint — the historical temperature
// setter is deprecated and returns ``410 Gone``.

import { BaseThreadService } from "../../generated/api/index.ts";
import { ModulesToolsService } from "../../generated/api/services/ModulesToolsService";
import { CommandResult } from "../entities/common/CommandResult.js";
import { ReadingSet } from "../entities/temperature/ReadingSet.js";
import { toReadingSet, toHeaterSetTargetRequest } from "../mappers/temperatureMapper.js";
import { describeError } from "../core/error-format.js";

/**
 * Fetch the current temperature readings from the base-thread
 * snapshot. Returns an empty ``ReadingSet`` if the snapshot is
 * missing or malformed.
 *
 * @returns {Promise<ReadingSet>}
 */
async function fetchReadings() {
  const snapshot = await BaseThreadService.getBaseThreadSnapshot();
  return toReadingSet(snapshot && snapshot.sensors);
}

/**
 * Set the target temperature for a heater. Routes through the
 * ``tools`` module's ``POST /tools/{tool_id}/target`` endpoint —
 * the historical ``/temperature/sensors/{name}/target`` endpoint
 * is deprecated and returns ``410 Gone``.
 *
 * @param {string} toolId Canonical tool id (the sensor name).
 * @param {number} target Target in degrees Celsius (0 turns the
 *   heater off).
 * @returns {Promise<CommandResult>}
 */
async function setTarget(toolId, target) {
  try {
    const response = await ModulesToolsService.setToolTarget(toolId, {
      tool_id: toolId,
      target,
    });
    return CommandResult.success({
      commandId: response && (response.command_id ?? response.tool_id),
      message: response && response.command ? response.command : "ok",
    });
  } catch (err) {
    return CommandResult.failure(describeError(err), {
      commandId: toolId,
      message: "Failed to set target",
    });
  }
}

export const temperatureFacade = Object.freeze({
  fetchReadings,
  setTarget,
});

export default temperatureFacade;
