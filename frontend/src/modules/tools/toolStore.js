// Tools module Pinia store.
//
// Owns the mock tool list (Issue #64 — the dynamic config
// implementation lands later) plus the two actions that dispatch
// HTTP POSTs to the backend router:
//
//   * :func:`sendSpindleCommand` — start / reverse / stop a spindle.
//   * :func:`sendExtruderCommand` — extrude or retract filament.
//
// Cross-store logging goes through :func:`useConsoleStore`, which
// is instantiated **inside** each action so the store can be
// imported during boot without tripping the
// "circular store initialisation" gotcha documented in
// ``.agent/AI_INSTRUCTIONS.md`` § 21.
//
// The store id is namespaced under the ``module_`` prefix per
// ``MODULE_SYSTEM_ROADMAP.md`` § 12 Gotcha #2 so it can never
// collide with the legacy top-level Pinia store ids.
//
// Reference: ``.agent/contracts/frontend-module.md`` § 5.

import { defineStore } from "pinia";
import { ref } from "vue";

import { useConsoleStore } from "../../stores/console.js";
import manifest from "./manifest.js";

// Issue #64 § 2 — hardcoded mock tools array. The two seeds below
// cover both supported tool types (spindle + extruder) so the
// panel has something to render regardless of which physical
// tools the operator actually has wired up.
const SEED_TOOLS = [
  {
    id: "spindle_main",
    name: "Main Spindle",
    type: "spindle",
    // ``actual_rpm`` is the live reading the panel would receive
    // via telemetry in a future revision. Hard-coded to 0 today.
    actual_rpm: 0,
    target_rpm: 0,
    set_speed: 10000,
  },
  {
    id: "extruder_1",
    name: "Extruder E0",
    type: "extruder",
    set_speed: 300,
    // ``distance_index`` maps into the logarithmic distance array
    // defined in ``ToolPanel.vue``. Index 2 ⇒ 10 mm — a sensible
    // mid-range default for a single click on either direction.
    distance_index: 2,
  },
];

// Pinia store id — see Gotcha #2. Built from the manifest id
// with the required ``module_`` prefix so it can never collide
// with the legacy top-level stores. The literal is constructed
// by concatenation so the store-id lint script
// (``frontend/scripts/check-store-ids.mjs``) doesn't false-
// positive on the comment above.
const STORE_ID = `module_${manifest.id}`;

/**
 * Fire-and-forget POST helper that:
 *
 *   1. Sends the JSON body to ``url``.
 *   2. Throws an :class:`Error` with the server-supplied detail
 *      when the response is non-2xx.
 *   3. Returns the parsed JSON payload on success.
 *
 * Centralising the error mapping keeps the action bodies focused
 * on UI concerns (optimistic state updates + console logging).
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