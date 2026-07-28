// Tools module Pinia store. Owns the mock tool list and the two
// actions that dispatch HTTP POSTs to the backend router
// (spindle + extruder). ``useConsoleStore`` is instantiated inside
// each action to avoid the circular-initialisation trap. See
// ``.agent/STATE.md`` § 2, § 9.

import { defineStore } from "pinia";
import { ref } from "vue";

import { useConsoleStore } from "../../stores/console.js";
import manifest from "./manifest.js";

// Mock tools array (the dynamic config implementation lands later).
// Seeds cover both supported tool types so the panel always has
// something to render.
const SEED_TOOLS = [
  {
    id: "spindle_main",
    name: "Main Spindle",
    type: "spindle",
    // Live reading the panel would receive via telemetry in a
    // future revision. Hard-coded to 0 today.
    actual_rpm: 0,
    target_rpm: 0,
    set_speed: 10000,
  },
  {
    id: "extruder_1",
    name: "Extruder E0",
    type: "extruder",
    set_speed: 300,
    // Index into the logarithmic distance array defined in
    // ``ToolPanel.vue``. Index 2 ⇒ 10 mm.
    distance_index: 2,
  },
];

// ``module_`` prefix prevents collisions with legacy top-level
// stores. See ``.agent/STATE.md`` § 2.
const STORE_ID = `module_${manifest.id}`;

/**
 * POST helper. Throws an Error with the server-supplied detail on
 * non-2xx, returns the parsed JSON on success. Centralising the
 * error mapping keeps the action bodies focused on UI concerns.
 *
 * @param {string} url
 * @param {Record<string, unknown>} body
 * @returns {Promise<Record<string, unknown>>}
 */
async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const text = await response.text();
      if (text) detail = text;
    } catch (_) {
      // Best-effort: statusText is fine when the body is empty.
    }
    throw new Error(`${response.status} ${detail}`);
  }
  return response.json();
}

export const useToolStore = defineStore(STORE_ID, () => {
  // --- reactive state ------------------------------------------- //
  // Mirror the SEED_TOOLS array with ``ref`` so future revisions
  // can call ``tools.value = await fetchConfig()`` to swap in
  // dynamic configuration without rewriting the panel.
  /** @type {import('vue').Ref<Array<Record<string, any>>>} */
  const tools = ref(SEED_TOOLS.map((tool) => ({ ...tool })));

  // --- actions -------------------------------------------------- //

  /**
   * Send a spindle command and optimistically mirror the new
   * target RPM on the matching tool so the panel reflects the
   * operator's intent immediately. Errors are routed to the
   * console store for visibility in the persistent log.
   *
   * @param {string} toolId
   * @param {"forward"|"backward"|"stop"} action
   * @param {number} speed
   */
  async function sendSpindleCommand(toolId, action, speed) {
    try {
      await postJson("/api/v1/modules/tools/spindle", {
        tool_id: toolId,
        action,
        speed,
      });
      // Optimistic UI update — only the target RPM changes from
      // the operator's perspective. ``actual_rpm`` would normally
      // come back via telemetry and is left untouched here.
      const tool = tools.value.find((t) => t.id === toolId);
      if (tool) {
        tool.target_rpm = action === "stop" ? 0 : speed;
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : String(err ?? "unknown error");
      useConsoleStore().error(`Spindle command failed: ${message}`);
    }
  }

  /**
   * Send an extrude / retract command. The panel computes the
   * signed distance from its logarithmic slider so the store
   * stays free of UI magic numbers.
   *
   * @param {string} toolId
   * @param {"extrude"|"retract"} action
   * @param {number} distance Positive mm (sign applied server-side).
   * @param {number} speed Feed rate in mm/min.
   */
  async function sendExtruderCommand(toolId, action, distance, speed) {
    try {
      await postJson("/api/v1/modules/tools/extruder", {
        tool_id: toolId,
        action,
        distance,
        speed,
      });
      useConsoleStore().info(
        `${action} ${distance}mm at ${speed}mm/min`,
      );
    } catch (err) {
      const message =
        err instanceof Error ? err.message : String(err ?? "unknown error");
      useConsoleStore().error(`Extruder command failed: ${message}`);
    }
  }

  // Public surface.
  return {
    tools,
    sendSpindleCommand,
    sendExtruderCommand,
  };
});

export default useToolStore;