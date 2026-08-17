// Tools module Pinia store. Consumes the operator-facing tool
// list from the shared base-thread snapshot
// (``stores/baseThread.js``) — the base-thread store owns the 1 Hz
// REST round-trip so the dashboard only issues one HTTP request
// per second for every slow stream (program progress, temperature
// sensors, tool list).
//
// All write actions (spindle / extruder / tool-target) go through
// the ``toolsFacade``; the store never hand-rolls ``fetch`` calls
// and never imports the generated OpenAPI client. Errors are
// routed through ``describeError`` so the console store sees the
// same envelope shape as every other module.

import { defineStore, storeToRefs } from "pinia";
import { computed, onScopeDispose, ref, watch } from "vue";

import { describeError } from "../../core/error-format";
import { useBaseThreadStore } from "../../stores/baseThread";
import { useConsoleStore } from "../../stores/console";
import { toolsFacade } from "../../facades/toolsFacade";
import manifest from "./manifest";

// ``module_`` prefix prevents collisions with legacy top-level
// stores.
const STORE_ID = `module_${manifest.id}`;

export const useToolStore = defineStore(STORE_ID, () => {
  // --- selection state (store-owned) ------------------------------ //
  const selectedToolId = ref(/** @type {string | null} */ (null));

  let stopToolsWatch = null;

  // --- base-thread consumer -------------------------------------- //
  const baseThread = useBaseThreadStore();
  // Legacy ``tools`` array (kept for the migration window) AND
  // the typed ``toolList: ToolList``. Consumers migrate one at a
  // time.
  const { tools, toolList } = storeToRefs(baseThread);

  const selectedTool = computed(() => {
    if (!selectedToolId.value) return null;
    if (toolList.value && typeof toolList.value.get === "function") {
      return toolList.value.get(selectedToolId.value) || null;
    }
    const list = baseThread.tools || [];
    return list.find((t) => t.id === selectedToolId.value) || null;
  });

  function setSelectedToolId(id) {
    selectedToolId.value = id;
  }

  async function refreshTools() {
    await baseThread.refresh();
  }

  // --- actions (all via toolsFacade) ------------------------------- //

  /**
   * Send a spindle command.
   */
  async function sendSpindleCommand(
    toolId,
    action,
    speed,
    masterOverride = 0,
    masterOverrideEnable = false,
    override = 1.0,
  ) {
    const result = await toolsFacade.controlSpindle(
      toolId,
      action,
      speed,
      masterOverride,
      masterOverrideEnable,
      override,
    );
    if (result.failed) {
      useConsoleStore().error(
        `Spindle command failed: ${describeError(result.failureReason)}`,
      );
    }
    return result;
  }

  /**
   * Send an extrude / retract command. Reads the current target
   * off the snapshot to avoid an extra round-trip.
   */
  async function sendExtruderCommand(toolId, action, distance, speed) {
    const tool = (baseThread.tools || []).find((t) => t.id === toolId);
    const currentTarget =
      tool && typeof tool.target === "number" ? tool.target : 0;
    const heaterAction = currentTarget > 0 ? "set" : "noop";

    const result = await toolsFacade.controlExtruder(
      toolId,
      action,
      distance,
      speed,
      currentTarget,
      heaterAction,
    );
    if (result.failed) {
      useConsoleStore().error(
        `Extruder command failed: ${describeError(result.failureReason)}`,
      );
    } else {
      useConsoleStore().info(
        `${action} ${distance}mm at ${speed}mm/min`,
      );
    }
    return result;
  }

  /**
   * Set the target temperature for a heating tool.
   */
  async function sendToolTarget(toolId, target) {
    const result = await toolsFacade.setTarget(toolId, target);
    if (result.failed) {
      useConsoleStore().error(
        `Tool target failed: ${describeError(result.failureReason)}`,
      );
    }
    return result;
  }

  // Auto-pick the first tool when none is selected.
  stopToolsWatch = watch(
    () => baseThread.tools,
    (next) => {
      if (!selectedToolId.value && Array.isArray(next) && next.length > 0) {
        selectedToolId.value = next[0].id;
      }
    },
    { immediate: true, deep: true },
  );

  onScopeDispose(() => {
    if (stopToolsWatch) {
      stopToolsWatch();
      stopToolsWatch = null;
    }
  });

  // Public surface.
  return {
    tools,
    toolList,
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
