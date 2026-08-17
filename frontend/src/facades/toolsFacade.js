// Tools facade. Single UI-facing API for the operator-facing
// tool list (read) and the spindle / extruder / heater write
// commands.
//
// Reads come from the shared base-thread snapshot. Two flavours:
//
//   * ``mapToolsWire(wires)`` — pure mapper the base-thread polling
//     loop calls every 1 Hz. Keeps the polling path efficient (no
//     extra HTTP round-trip per tick).
//   * ``fetchTools()`` — async helper for callers that want a
//     fresh pull right now (e.g. ``toolStore.refreshToolsList``
//     after a deploy). Issues a single snapshot HTTP call and
//     maps the result.
//
// Writes return a :class:`CommandResult` so callers never have
// to try/catch — the facade wraps every generated-client throw
// in ``CommandResult.failure(...)``.

import {
  ModulesToolsService,
} from "../../generated/api/services/ModulesToolsService";
import { BaseThreadService } from "../../generated/api/index.ts";
import { CommandResult } from "../entities/common/CommandResult.js";
import { ToolList } from "../entities/tools/ToolList.js";
import {
  toSpindleCommand,
  toExtruderCommand,
  toHeaterCommand,
  toToolList,
} from "../mappers/toolsMapper.js";
import { describeError } from "../core/error-format.js";

// --- Reads ---------------------------------------------------------------

/**
 * Pure mapper — wraps ``toToolList`` so the facade owns the
 * wire-shape → entity translation. The base-thread polling loop
 * calls this on every tick; the mapper is idempotent and cheap.
 *
 * @param {Array<object>|null|undefined} wires
 * @returns {ToolList}
 */
function mapToolsWire(wires) {
  return toToolList(wires);
}

/**
 * Pull a fresh tool list straight from the snapshot endpoint.
 * Used by ``toolStore.refreshToolsList`` for post-deploy refreshes
 * where the 1 Hz polling cadence is too slow.
 *
 * @returns {Promise<ToolList>}
 */
async function fetchTools() {
  const snapshot = await BaseThreadService.getBaseThreadSnapshot();
  return mapToolsWire(snapshot && Array.isArray(snapshot.tools) ? snapshot.tools : []);
}

// --- Writes --------------------------------------------------------------

async function _commandResultFrom(promise, commandId) {
  try {
    await promise;
    return CommandResult.success({ commandId });
  } catch (err) {
    return CommandResult.failure(describeError(err), {
      commandId,
      message: "Tool command failed",
    });
  }
}

/**
 * @param {string} toolId
 * @param {"forward"|"backward"|"stop"} action
 * @param {number} speed
 * @param {number} [masterOverride]
 * @param {boolean} [masterOverrideEnable]
 * @param {number} [override]
 * @returns {Promise<CommandResult>}
 */
async function controlSpindle(
  toolId,
  action,
  speed,
  masterOverride = 0,
  masterOverrideEnable = false,
  override = 1.0,
) {
  try {
    const wire = toSpindleCommand({
      toolId,
      action,
      speed,
      masterOverride,
      masterOverrideEnable,
      override,
    });
    const response = await ModulesToolsService.controlSpindle(wire);
    return CommandResult.success({
      commandId: response && (response.tool_id ?? toolId),
      message: response && response.command ? response.command : "ok",
    });
  } catch (err) {
    return CommandResult.failure(describeError(err), {
      commandId: toolId,
      message: "Spindle command failed",
    });
  }
}

/**
 * @param {string} toolId
 * @param {"extrude"|"retract"} action
 * @param {number} distance Positive mm.
 * @param {number} speed Feed rate mm/min.
 * @param {number} heaterTarget Current target temp to forward.
 * @param {"set"|"noop"} [heaterAction]
 * @returns {Promise<CommandResult>}
 */
async function controlExtruder(
  toolId,
  action,
  distance,
  speed,
  heaterTarget,
  heaterAction = "set",
) {
  try {
    const wire = toExtruderCommand({
      toolId,
      action,
      distance,
      speed,
      heaterTarget,
      heaterAction,
    });
    const response = await ModulesToolsService.controlExtruder(wire);
    return CommandResult.success({
      commandId: response && (response.tool_id ?? toolId),
      message: response && response.command ? response.command : "ok",
    });
  } catch (err) {
    return CommandResult.failure(describeError(err), {
      commandId: toolId,
      message: "Extruder command failed",
    });
  }
}

/**
 * Set a heater's target temperature.
 *
 * @param {string} toolId
 * @param {number} target Celsius. 0 turns the heater off.
 * @returns {Promise<CommandResult>}
 */
async function setTarget(toolId, target) {
  try {
    const wire = toHeaterCommand({ toolId, target });
    const response = await ModulesToolsService.setToolTarget(toolId, wire);
    return CommandResult.success({
      commandId: response && (response.tool_id ?? toolId),
      message: response && response.command ? response.command : "ok",
    });
  } catch (err) {
    return CommandResult.failure(describeError(err), {
      commandId: toolId,
      message: "Tool target failed",
    });
  }
}

export const toolsFacade = Object.freeze({
  // Reads
  mapToolsWire,
  fetchTools,
  // Writes
  controlSpindle,
  controlExtruder,
  setTarget,
});

export default toolsFacade;
