// Tools module Pinia store. Consumes the operator-facing tool list
// from the shared base-thread snapshot
// (``stores/baseThread.js``) — the base-thread store owns the 1 Hz
// REST round-trip so the dashboard only issues one HTTP request per
// second for every slow stream (program progress, temperature
// sensors, tool list). All write actions (spindle / extruder /
// tool-target) go through the OpenAPI-generated
// ``ModulesToolsService`` client; the store never hand-rolls
// ``fetch`` calls. Errors are routed through
// :func:`core/error-format.js` ``describeError`` so the console
// store sees the same envelope shape as every other module.
//
// See ``.agent/context/LESSONS_LEARNED.md`` § 2.7 (never hand-roll
// HTTP when a generated service exists) and § 2.6 (cross-module
// reactivity needs ``deep: true`` + sync initial pull).

import { defineStore, storeToRefs } from "pinia";
import { computed, onScopeDispose, ref, watch } from "vue";

import { describeError } from "../../core/error-format.js";
import { ModulesToolsService } from "../../../generated/api/services/ModulesToolsService";
import { useBaseThreadStore } from "../../stores/baseThread.js";
import { useConsoleStore } from "../../stores/console.js";
import manifest from "./manifest.js";

// ``module_`` prefix prevents collisions with legacy top-level
// stores. See ``.agent/STATE.md`` § 2.
const STORE_ID = `module_${manifest.id}`;

export const useToolStore = defineStore(STORE_ID, () => {
  // --- selection state (store-owned) ------------------------------ //
  // The tool list itself is owned by ``useBaseThreadStore`` — see
  // the watcher at the bottom of this closure. Selection is the
  // only piece of state that genuinely belongs to the tools
  // module.
  const selectedToolId = ref(/** @type {string | null} */ (null));

  // --- non-reactive handles ------------------------------------- //
  // Stop handle for the base-thread tools watcher. Set when the
  // watcher is registered (immediately below) and cleared by
  // ``onScopeDispose``.
  let stopToolsWatch = null;

  // --- base-thread consumer -------------------------------------- //
  // The base-thread store already polls
  // ``GET /api/v1/base_thread/snapshot`` every second; the
  // ``tools`` field on the snapshot is populated by
  // ``routers/base_thread.py::_collect_tools`` which delegates to
  // ``modules/tools/router.py::_collect_tools``. Consuming it here
  // keeps the tools panel in sync with every other slow stream
  // without a second timer.
  const baseThread = useBaseThreadStore();
  // ``storeToRefs`` keeps reactivity through the proxy so consumers
  // that destructure ``tools`` get a reactive ref rather than a
  // stale snapshot. ``storeToRefs`` is mandatory — see
  // ``.agent/context/LESSONS_LEARNED.md`` § 2.3.
  const { tools } = storeToRefs(baseThread);

  // The currently-selected tool. ``null`` when the list is empty
  // or the operator's selection points at a tool the backend
  // dropped.
  const selectedTool = computed(() => {
    if (!selectedToolId.value) return null;
    const list = baseThread.tools || [];
    return list.find((t) => t.id === selectedToolId.value) || null;
  });

  // --- helpers -------------------------------------------------- //

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
   * Refresh the base-thread snapshot out-of-band. Kept on the
   * public surface so a future "Refresh now" button can force a
   * re-read without waiting for the next 1 Hz tick. Delegates to
   * the base-thread store — the tools store never owns its own
   * polling interval (see ``.agent/context/LESSONS_LEARNED.md``
   * § 2.6 for the cross-module reactivity rules).
   */
  async function refreshTools() {
    await baseThread.refresh();
  }

  // --- actions (all via ModulesToolsService) --------------------- //

  /**
   * Send a spindle command. The cards own their own optimistic
   * ``targetRpm`` local ref (see SpindleCard.vue) — the store no
   * longer mutates the tool object because the base-thread
   * snapshot replaces it on every 1 s poll anyway. Errors are
   * routed to the console store via ``describeError`` so the
   * operator sees the same envelope shape as every other module.
   *
   * ``masterOverride`` and ``masterOverrideEnable`` enable the
   * backend's master-override bypass: when ``masterOverrideEnable``
   * is true, the dispatch uses ``masterOverride`` RPM directly and
   * the ``override`` pin is left untouched. The default values
   * (``0`` / ``false``) preserve the legacy behaviour for callers
   * that don't know about the bypass (notably AnalogSpindleCard).
   *
   * ``override`` is the relative override factor (0.0–2.0; 1.0 =
   * 100%) written to ``halui.spindle.override.scale`` before
   * every M-code dispatch. Ignored when ``masterOverrideEnable``
   * is true. Defaults to ``1.0`` (the LinuxCNC native default).
   *
   * @param {string} toolId
   * @param {"forward"|"backward"|"stop"} action
   * @param {number} speed
   * @param {number} [masterOverride=0] Absolute RPM applied when masterOverrideEnable is true.
   * @param {boolean} [masterOverrideEnable=false] Bypass speed/override scaling and force masterOverride RPM.
   * @param {number} [override=1.0] Relative override factor (0.0–2.0; ignored when masterOverrideEnable is true).
   */
  async function sendSpindleCommand(
    toolId,
    action,
    speed,
    masterOverride = 0,
    masterOverrideEnable = false,
    override = 1.0,
  ) {
    try {
      await ModulesToolsService.controlSpindle({
        tool_id: toolId,
        action,
        speed,
        master_override: masterOverride,
        master_override_enable: masterOverrideEnable,
        override,
      });
    } catch (err) {
      useConsoleStore().error(
        `Spindle command failed: ${describeError(err)}`,
      );
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
      await ModulesToolsService.controlExtruder({
        tool_id: toolId,
        action,
        distance,
        speed,
      });
      useConsoleStore().info(
        `${action} ${distance}mm at ${speed}mm/min`,
      );
    } catch (err) {
      useConsoleStore().error(
        `Extruder command failed: ${describeError(err)}`,
      );
    }
  }

  /**
   * Set the target temperature for a heating tool (extruder /
   * heated_bed). The router looks up the tool's ``sensor``
   * reference and dispatches ``set_temperature`` to the hardware
   * layer; the temperature module owns the sensor channel, the
   * tools module owns the operator-facing target command.
   *
   * @param {string} toolId
   * @param {number} target Degrees Celsius (0 turns the heater off).
   */
  async function sendToolTarget(toolId, target) {
    try {
      await ModulesToolsService.setToolTarget(toolId, {
        tool_id: toolId,
        target,
      });
    } catch (err) {
      useConsoleStore().error(
        `Tool target failed: ${describeError(err)}`,
      );
    }
  }

  // --- watch the base-thread snapshot --------------------------- //
  // ``deep: true`` because Pinia's OPTIONS-API top-level
  // reassignment in the baseThread store does not always
  // rebroadcast across module boundaries via the proxy; see
  // ``.agent/context/LESSONS_LEARNED.md`` § 2.6. The payload is a
  // handful of tool rows so the deep-traversal cost is
  // negligible. The ``immediate: true`` flag ensures the watcher
  // fires on subscription so the first frame renders populated
  // tools, even if the panel mounts before the first 1 Hz tick.
  stopToolsWatch = watch(
    () => baseThread.tools,
    (next) => {
      if (!selectedToolId.value && Array.isArray(next) && next.length > 0) {
        selectedToolId.value = next[0].id;
      }
    },
    { immediate: true, deep: true },
  );

  // Auto-clean the watcher when the pinia scope goes away
  // (component unmount, app teardown) so the subscriber cannot
  // leak across navigation. See ``.agent/STATE.md`` § 10.
  onScopeDispose(() => {
    if (stopToolsWatch) {
      stopToolsWatch();
      stopToolsWatch = null;
    }
  });

  // Public surface.
  return {
    tools,
    selectedToolId,
    selectedTool,
    setSelectedToolId,
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