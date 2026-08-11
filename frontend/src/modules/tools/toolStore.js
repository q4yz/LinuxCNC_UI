// Tools module Pinia store. Owns the backend-driven tool list, the
// single-tool selection state, and the three actions that dispatch
// HTTP POSTs to the backend router (spindle + extruder + tool
// target). ``useConsoleStore`` is instantiated inside each action
// to avoid the circular-initialisation trap. See ``.agent/STATE.md``
// § 2, § 9.
//
// The list is loaded from ``GET /api/v1/modules/tools/tools`` and
// optionally pushed via the ``state.tools`` event-bus topic — the
// poll is the source of truth, the subscription just provides
// faster updates. Mirrors the temperature module's loader pattern.
//
// Tool object shape (from hardware.json ``tools[]``):
//
//   {
//     id, name,
//     type: "extruder" | "spindle_digital" | "spindle_analog"
//         | "heated_bed" | "laser",
//     // spindle shared
//     min_rpm, max_rpm,
//     // spindle analog only
//     pwm_pin, enable_pin,
//     // spindle digital only
//     signal_*: ...,
//     // extruder + heated_bed only (heat fields)
//     sensor, heater_pin, fan, control, min_temp, max_temp,
//   }
//
// Tools with a sensor / heater_pin (extruder + heated_bed) also
// surface on the temperature chart via the temperature_sensors[] +
// tools[] cross-reference in hardware.json. The ToolPanel renders
// one card per tool, dispatched by ``type``.

import { defineStore, storeToRefs } from "pinia";
import { computed, onScopeDispose, ref } from "vue";

import { eventBus } from "../../core/modules/event-bus.js";
import { useConsoleStore } from "../../stores/console.js";
import manifest from "./manifest.js";

const TOPIC = "state.tools";

// 1 s cadence matches the temperature module; the chart shape is
// not configurable on the tools panel so a constant is sufficient.
const DEFAULT_POLL_MS = 1_000;

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
  /** @type {import('vue').Ref<Array<Record<string, any>>>} */
  const tools = ref([]);
  // Currently-selected tool id. ``null`` until the first ingest
  // populates ``tools``; the panel picks the first tool as the
  // default at that point. See ``ingest`` below.
  const selectedToolId = ref(/** @type {string | null} */ (null));
  const pollMs = ref(DEFAULT_POLL_MS);

  // --- non-reactive handles ------------------------------------- //
  let pollHandle = null;
  let busUnsub = null;
  // Tracks whether the store has been started by ``onMounted`` so
  // hot-reloads / double-mounts don't accumulate intervals.
  let running = false;

  // --- computed ------------------------------------------------- //

  // The tool the panel should render. ``null`` until at least one
  // tool is available or while the operator's selection points at a
  // tool the backend dropped.
  const selectedTool = computed(() => {
    if (!selectedToolId.value) return null;
    return tools.value.find((t) => t.id === selectedToolId.value) || null;
  });

  // --- actions -------------------------------------------------- //

  /**
   * Update the active tool. The chip row in ``ToolPanel.vue``
   * calls this on click; passing an unknown id is a no-op for the
   * ``selectedTool`` getter.
   *
   * @param {string} id
   */
  function setSelectedToolId(id) {
    selectedToolId.value = id;
  }

  /**
   * Pull the live tool state from the backend and ingest it. The
   * ``GET /api/v1/modules/tools/tools`` endpoint returns
   * ``{ tools: [...] }`` (canonical) — ``ingest`` also tolerates
   * ``{ items: [...] }`` or a raw array so the loader doesn't have
   * to be rewritten when the backend shape is finalised.
   */
  async function refreshTools() {
    try {
      const data = await fetch(
        `/api/v1/modules/${manifest.id}/tools`,
      ).then(async (r) => (r.ok ? r.json() : null));
      if (data) ingest(data);
    } catch (_) {
      // Best-effort — keep the last known list visible.
    }
  }

  /**
   * Normalise the backend payload and merge it into ``tools``.
   * Accepts a raw array, ``{ tools: [...] }``, or ``{ items: [...]
   * }``; auto-selects the first tool when the list grows from
   * empty so the panel has something to render on first arrival.
   *
   * @param {*} payload
   */
  function ingest(payload) {
    if (!payload) return;
    let next = null;
    if (Array.isArray(payload)) {
      next = payload;
    } else if (payload.tools && Array.isArray(payload.tools)) {
      next = payload.tools;
    } else if (payload.items && Array.isArray(payload.items)) {
      next = payload.items;
    }
    if (!next) return;
    // Shallow-clone each row so the store never mutates the
    // upstream payload in place. Telemetry payloads are
    // deep-frozen by the event bus.
    tools.value = next.map((tool) => ({ ...tool }));
    // Auto-pick the first tool only when nothing is selected yet —
    // never override an explicit operator choice.
    if (!selectedToolId.value && tools.value.length > 0) {
      selectedToolId.value = tools.value[0].id;
    }
  }

  function start() {
    if (running) return;
    running = true;
    // Fetch tool state immediately so the panel isn't empty on
    // first render, then poll at the configured cadence.
    refreshTools();
    pollHandle = setInterval(refreshTools, pollMs.value);
  }

  function stop() {
    running = false;
    if (pollHandle !== null) {
      clearInterval(pollHandle);
      pollHandle = null;
    }
  }

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
   * Send an extrude / retract command. The card computes the
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

  /**
   * Set the target temperature for a heating tool (extruder /
   * heated_bed). Mirrors the temperature module's per-sensor
   * ``POST /api/v1/modules/temperature/sensors/{name}/target``
   * contract, but keyed on tool id rather than sensor name — the
   * temperature module owns the sensor channel, the tools module
   * owns the operator-facing target command.
   *
   * @param {string} toolId
   * @param {number} target Degrees Celsius (0 turns the heater off).
   */
  async function sendToolTarget(toolId, target) {
    try {
      await postJson(
        `/api/v1/modules/tools/tools/${encodeURIComponent(toolId)}/target`,
        {
          tool_id: toolId,
          target,
        },
      );
    } catch (err) {
      const message =
        err instanceof Error ? err.message : String(err ?? "unknown error");
      useConsoleStore().error(`Tool target failed: ${message}`);
    }
  }

  // The bus delivers deep-frozen payloads; we shallow-clone before
  // storing. See ``.agent/STATE.md`` § 3.
  busUnsub = eventBus.subscribe(TOPIC, (_topic, payload) => {
    ingest(payload);
  });

  // Auto-stop when the pinia scope goes away (component unmount,
  // app teardown) so the polling interval cannot leak across
  // navigation. See ``.agent/STATE.md`` § 10.
  onScopeDispose(() => {
    stop();
    if (busUnsub) {
      busUnsub();
      busUnsub = null;
    }
  });

  // Public surface.
  return {
    tools,
    selectedToolId,
    selectedTool,
    pollMs,
    setSelectedToolId,
    ingest,
    start,
    stop,
    refreshTools,
    sendSpindleCommand,
    sendExtruderCommand,
    sendToolTarget,
  };
});

/**
 * Convenience wrapper around ``storeToRefs`` so callers can
 * destructure the reactive state without losing reactivity.
 */
export function useToolRefs() {
  const store = useToolStore();
  return { store, ...storeToRefs(store) };
}

export default useToolStore;